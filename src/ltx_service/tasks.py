from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .errors import api_error
from .executor import ExecutorAdapter
from .ids import new_id
from .models import ApiKey, Asset, TaskAttempt, VideoTask
from .storage import ObjectStorageAdapter
from .usage import record_usage, summarize_usage_by_api_key
from .worker_registry import list_available_workers
from .workflows import get_published_workflow

RETRYABLE_ERRORS = {"transient", "worker_crash"}
NON_RETRYABLE_ERRORS = {"invalid_input", "policy_rejected"}
MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class DispatchOutcome:
    dispatched: bool
    attempt: TaskAttempt | None = None
    reason: str | None = None
    worker_id: str | None = None


def create_video_task(
    session: Session,
    api_key: ApiKey,
    payload: dict,
    idempotency_key: str | None,
) -> tuple[VideoTask, int]:
    if idempotency_key:
        existing = session.scalar(
            select(VideoTask).where(
                VideoTask.api_key_id == api_key.id,
                VideoTask.idempotency_key == idempotency_key,
            )
        )
        if existing:
            estimated = _estimated_seconds(session, existing.workflow_version_id, existing.profile)
            return existing, estimated

    if payload["mode"] == "image_to_video":
        image_asset_id = payload.get("image_asset_id")
        if not image_asset_id:
            raise api_error(422, "REQUEST_IMAGE_REQUIRED", "image_asset_id is required for image_to_video")
        asset = session.get(Asset, image_asset_id)
        if not asset or asset.api_key_id != api_key.id or asset.status != "uploaded":
            raise api_error(422, "REQUEST_INVALID_PARAMETER", "image_asset_id is invalid or not uploaded")

    if api_key.quota_task_limit is not None:
        task_count = session.scalar(select(func.count()).select_from(VideoTask).where(VideoTask.api_key_id == api_key.id))
        if task_count is not None and task_count >= api_key.quota_task_limit:
            raise api_error(429, "QUOTA_EXCEEDED", "API key quota exceeded")

    workflow_version, profile = get_published_workflow(session, payload["mode"], payload["profile"])
    task = VideoTask(
        id=new_id("tsk"),
        api_key_id=api_key.id,
        mode=payload["mode"],
        status="queued",
        profile=payload["profile"],
        workflow_version_id=workflow_version.id,
        request_params=payload,
        idempotency_key=idempotency_key,
        progress_stage="queued",
        progress_percent=0,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return task, profile.estimated_gpu_seconds


def dispatch_next(session: Session, executor: ExecutorAdapter) -> DispatchOutcome:
    task = session.scalar(select(VideoTask).where(VideoTask.status == "queued").order_by(VideoTask.created_at.asc()))
    if not task:
        return DispatchOutcome(dispatched=False)
    if executor.executor_type == "gpu-worker":
        return _dispatch_to_gpu_worker(session, executor, task)
    task.status = "running"
    task.progress_stage = "running"
    task.progress_percent = 10
    task.attempt_count += 1
    attempt = TaskAttempt(
        id=new_id("att"),
        task_id=task.id,
        attempt_no=task.attempt_count,
        executor_type=executor.executor_type,
        status="running",
    )
    session.add(attempt)
    session.commit()
    session.refresh(attempt)
    return DispatchOutcome(dispatched=True, attempt=attempt)


def _dispatch_to_gpu_worker(session: Session, executor: ExecutorAdapter, task: VideoTask) -> DispatchOutcome:
    workers = list_available_workers(session, mode=task.mode, profile=task.profile)
    if not workers:
        task.error_code = "CAPACITY_UNAVAILABLE"
        task.progress_stage = "queued"
        task.progress_percent = 0
        session.commit()
        return DispatchOutcome(dispatched=False, reason="CAPACITY_UNAVAILABLE")

    worker = workers[0]
    task.status = "dispatching"
    task.progress_stage = "dispatching"
    task.progress_percent = 5
    task.error_code = None
    task.attempt_count += 1
    attempt = TaskAttempt(
        id=new_id("att"),
        task_id=task.id,
        attempt_no=task.attempt_count,
        executor_type=executor.executor_type,
        worker_id=worker.id,
        status="assigned",
    )
    session.add(attempt)
    session.flush()

    assignment = executor.assign(task, attempt, worker)
    if assignment.status == "accepted":
        attempt.status = "running"
        task.status = "running"
        task.progress_stage = "running"
        task.progress_percent = 10
        worker.status = "busy"
        worker.queue_depth = 1
        worker.current_attempt_id = attempt.id
        session.commit()
        session.refresh(attempt)
        return DispatchOutcome(dispatched=True, attempt=attempt, worker_id=worker.id)

    attempt.status = "failed"
    attempt.error_class = assignment.error_class
    attempt.finished_at = datetime.now(UTC)
    task.error_code = assignment.error_code
    worker.status = "idle"
    worker.queue_depth = 0
    worker.current_attempt_id = None
    if _should_retry(assignment.error_class, task.attempt_count):
        task.status = "queued"
        task.progress_stage = "queued"
        task.progress_percent = 0
    else:
        task.status = "failed"
        task.progress_stage = "failed"
        task.progress_percent = 100
        task.completed_at = datetime.now(UTC)
        record_usage(session, task, "failed", 0)
    session.commit()
    session.refresh(attempt)
    return DispatchOutcome(
        dispatched=False,
        attempt=attempt,
        reason=assignment.error_code,
        worker_id=worker.id,
    )


def complete_running(session: Session, storage: ObjectStorageAdapter, executor: ExecutorAdapter) -> VideoTask | None:
    if executor.executor_type != "mock-local":
        return None
    attempt = session.scalar(select(TaskAttempt).where(TaskAttempt.status == "running").order_by(TaskAttempt.started_at.asc()))
    if not attempt:
        return None
    task = session.get(VideoTask, attempt.task_id)
    if not task:
        attempt.status = "abandoned"
        attempt.finished_at = datetime.now(UTC)
        session.commit()
        return None
    result = executor.execute(task, attempt)
    attempt.actual_runtime_seconds = result.runtime_seconds
    attempt.finished_at = datetime.now(UTC)

    if result.status == "succeeded":
        if result.output_bytes is None:
            raise api_error(500, "EXECUTOR_INVALID_RESULT", "Executor succeeded without output")
        output = Asset(
            id=new_id("ast"),
            api_key_id=task.api_key_id,
            task_id=task.id,
            kind="video",
            storage_uri=storage.uri_for("outputs", task.id, "result.mp4"),
            content_type=result.output_content_type,
            size_bytes=0,
            status="uploaded",
        )
        output.size_bytes = storage.write_bytes(output.storage_uri, result.output_bytes)
        session.add(output)
        attempt.status = "succeeded"
        task.status = "succeeded"
        task.progress_stage = "completed"
        task.progress_percent = 100
        task.error_code = None
        task.completed_at = datetime.now(UTC)
        record_usage(session, task, "succeeded", result.runtime_seconds)
        session.commit()
        session.refresh(task)
        return task

    attempt.status = "failed"
    attempt.error_class = result.error_class
    task.error_code = result.error_code
    if _should_retry(result.error_class, task.attempt_count):
        task.status = "queued"
        task.progress_stage = "queued"
        task.progress_percent = 0
    else:
        task.status = "failed"
        task.progress_stage = "failed"
        task.progress_percent = 100
        task.completed_at = datetime.now(UTC)
        record_usage(session, task, "failed", result.runtime_seconds)
    session.commit()
    session.refresh(task)
    return task


def manual_retry(session: Session, task_id: str) -> VideoTask:
    task = session.get(VideoTask, task_id)
    if not task:
        raise api_error(404, "TASK_NOT_FOUND", "Task not found")
    if task.status != "failed":
        raise api_error(409, "TASK_NOT_RETRYABLE", "Only failed tasks can be retried manually")
    if task.attempt_count >= MAX_ATTEMPTS:
        task.attempt_count = MAX_ATTEMPTS - 1
    task.status = "queued"
    task.progress_stage = "queued"
    task.progress_percent = 0
    task.error_code = None
    session.commit()
    session.refresh(task)
    return task


def cancel_task(session: Session, api_key: ApiKey, task_id: str) -> VideoTask:
    task = get_task_for_api_key(session, api_key, task_id)
    if task.status not in {"queued", "running"}:
        raise api_error(409, "TASK_NOT_CANCELABLE", "Current task status cannot be canceled")
    task.status = "canceled"
    task.progress_stage = "canceled"
    task.progress_percent = 100
    task.completed_at = datetime.now(UTC)
    running_attempts = session.scalars(
        select(TaskAttempt).where(TaskAttempt.task_id == task.id, TaskAttempt.status == "running")
    ).all()
    for attempt in running_attempts:
        attempt.status = "canceled"
        attempt.finished_at = datetime.now(UTC)
    session.commit()
    session.refresh(task)
    return task


def get_task_for_api_key(session: Session, api_key: ApiKey, task_id: str) -> VideoTask:
    task = session.get(VideoTask, task_id)
    if not task or task.api_key_id != api_key.id:
        raise api_error(404, "TASK_NOT_FOUND", "Task not found")
    return task


def _should_retry(error_class: str | None, attempt_count: int) -> bool:
    return error_class in RETRYABLE_ERRORS and attempt_count < MAX_ATTEMPTS


def _estimated_seconds(session: Session, workflow_version_id: str, profile: str) -> int:
    from .models import WorkflowProfile

    workflow_profile = session.scalar(
        select(WorkflowProfile).where(
            WorkflowProfile.workflow_version_id == workflow_version_id,
            WorkflowProfile.profile == profile,
        )
    )
    return workflow_profile.estimated_gpu_seconds if workflow_profile else 0


def usage_summary(session: Session) -> list[dict]:
    return summarize_usage_by_api_key(session)
