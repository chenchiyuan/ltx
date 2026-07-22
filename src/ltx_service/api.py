from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Body, Depends, Header, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .assets import (
    create_upload_asset,
    ensure_upload_size,
    expires_at,
    get_owned_asset,
    upload_asset_content,
)
from .dependencies import AppState, require_admin_token, require_api_key, require_worker_token
from .errors import api_error
from .executor import ExecutorAdapter
from .models import ApiKey, Asset, TaskAttempt, VideoTask, WorkflowProfile, WorkflowTemplate, WorkflowVersion
from .schemas import (
    Progress,
    TaskResultResponse,
    TaskStatusResponse,
    UploadCreate,
    UploadCreated,
    VideoGenerationCreate,
    VideoGenerationCreated,
    WorkerHeartbeat,
    WorkerAttemptEvent,
    WorkerRegister,
)
from .storage import ObjectStorageAdapter
from .tasks import (
    cancel_task,
    apply_worker_attempt_event,
    complete_running,
    create_video_task,
    dispatch_next,
    get_task_for_api_key,
    manual_retry,
    usage_summary,
)
from .worker_registry import heartbeat_worker, list_workers, register_worker, serialize_worker
from .workflows import create_workflow_version, rollback_workflow, set_workflow_status


def build_router(state: AppState, get_session, executor: ExecutorAdapter) -> APIRouter:
    router = APIRouter()
    api_auth = require_api_key(get_session)
    admin_auth = require_admin_token(state.admin_token)
    worker_auth = require_worker_token(state.worker_token)

    @router.get("/health")
    def health(session: Session = Depends(get_session)):
        db_ok = bool(session.execute(select(1)).scalar_one())
        storage_health = state.storage.health()
        storage_ok = bool(storage_health.get("healthy"))
        executor_health = executor.health()
        return {
            "status": "ok" if db_ok and storage_ok else "degraded",
            "web": "ok",
            "database": "ok" if db_ok else "failed",
            "storage": "ok" if storage_ok else "failed",
            "storage_detail": storage_health,
            "executor": executor_health,
        }

    @router.get("/metrics", response_class=PlainTextResponse)
    def metrics(session: Session = Depends(get_session)):
        tasks = session.scalars(select(VideoTask)).all()
        lines = ["# HELP ltx_tasks_total Total tasks by status", "# TYPE ltx_tasks_total counter"]
        for status in sorted({task.status for task in tasks} | {"queued", "running", "succeeded", "failed"}):
            count = sum(1 for task in tasks if task.status == status)
            lines.append(f'ltx_tasks_total{{status="{status}"}} {count}')
        attempts = session.scalars(select(TaskAttempt)).all()
        lines.append("# HELP ltx_attempts_total Total attempts")
        lines.append("# TYPE ltx_attempts_total counter")
        lines.append(f"ltx_attempts_total {len(attempts)}")
        lines.append("# HELP ltx_task_attempts_total Tasks by attempt count")
        lines.append("# TYPE ltx_task_attempts_total gauge")
        for attempt_count in sorted({task.attempt_count for task in tasks} | {0, 1, 2, 3}):
            count = sum(1 for task in tasks if task.attempt_count == attempt_count)
            lines.append(f'ltx_task_attempts_total{{attempt_count="{attempt_count}"}} {count}')
        completed_attempts = [attempt for attempt in attempts if attempt.actual_runtime_seconds is not None]
        average_runtime = (
            sum(attempt.actual_runtime_seconds or 0 for attempt in completed_attempts) / len(completed_attempts)
            if completed_attempts
            else 0
        )
        lines.append("# HELP ltx_generation_runtime_seconds_avg Average mock executor runtime seconds")
        lines.append("# TYPE ltx_generation_runtime_seconds_avg gauge")
        lines.append(f"ltx_generation_runtime_seconds_avg {average_runtime:.3f}")
        lines.append("# HELP ltx_task_failures_total Failed tasks by error code")
        lines.append("# TYPE ltx_task_failures_total counter")
        for error_code in sorted({task.error_code for task in tasks if task.error_code}):
            count = sum(1 for task in tasks if task.error_code == error_code)
            lines.append(f'ltx_task_failures_total{{error_code="{error_code}"}} {count}')
        lines.append("# HELP ltx_attempt_failures_total Failed attempts by error class")
        lines.append("# TYPE ltx_attempt_failures_total counter")
        for error_class in sorted({attempt.error_class for attempt in attempts if attempt.error_class}):
            count = sum(1 for attempt in attempts if attempt.error_class == error_class)
            lines.append(f'ltx_attempt_failures_total{{error_class="{error_class}"}} {count}')
        succeeded = sum(1 for task in tasks if task.status == "succeeded")
        failed = sum(1 for task in tasks if task.status == "failed")
        total_terminal = succeeded + failed
        success_rate = succeeded / total_terminal if total_terminal else 0
        lines.append("# HELP ltx_task_success_rate Terminal task success rate")
        lines.append("# TYPE ltx_task_success_rate gauge")
        lines.append(f"ltx_task_success_rate {success_rate:.3f}")
        return "\n".join(lines) + "\n"

    @router.post("/v1/assets/uploads", response_model=UploadCreated)
    def create_upload(
        payload: UploadCreate,
        request: Request,
        api_key: ApiKey = Depends(api_auth),
        session: Session = Depends(get_session),
    ):
        asset = create_upload_asset(
            session,
            state.storage,
            api_key,
            payload.filename,
            payload.content_type,
            payload.size_bytes,
        )
        upload_url = str(request.url_for("put_asset_content", asset_id=asset.id))
        return UploadCreated(asset_id=asset.id, upload_url=upload_url, expires_at=expires_at(30))

    @router.put("/v1/assets/{asset_id}/content", name="put_asset_content")
    async def put_asset_content(
        asset_id: str,
        request: Request,
        api_key: ApiKey = Depends(api_auth),
        session: Session = Depends(get_session),
    ):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            ensure_upload_size(int(content_length))
        data = await request.body()
        asset = upload_asset_content(session, state.storage, api_key, asset_id, data)
        return {"asset_id": asset.id, "status": asset.status, "size_bytes": asset.size_bytes}

    @router.get("/v1/assets/{asset_id}/content", name="get_asset_content")
    def get_asset_content(
        asset_id: str,
        api_key: ApiKey = Depends(api_auth),
        session: Session = Depends(get_session),
    ):
        asset = get_owned_asset(session, api_key, asset_id)
        if asset.status != "uploaded":
            raise api_error(404, "ASSET_NOT_FOUND", "Asset content is not available")
        return Response(content=state.storage.read_bytes(asset.storage_uri), media_type=asset.content_type)

    @router.post("/v1/video-generations", response_model=VideoGenerationCreated)
    def create_generation(
        payload: VideoGenerationCreate,
        api_key: ApiKey = Depends(api_auth),
        session: Session = Depends(get_session),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        task, estimated = create_video_task(session, api_key, payload.model_dump(), idempotency_key)
        return VideoGenerationCreated(
            task_id=task.id,
            status=task.status,
            profile=task.profile,
            estimated_gpu_seconds=estimated,
            created_at=task.created_at.isoformat() if task.created_at else None,
        )

    @router.get("/v1/video-generations/{task_id}", response_model=TaskStatusResponse)
    def get_generation(task_id: str, api_key: ApiKey = Depends(api_auth), session: Session = Depends(get_session)):
        task = get_task_for_api_key(session, api_key, task_id)
        return _task_status_response(task)

    @router.post("/v1/video-generations/{task_id}/cancel", response_model=TaskStatusResponse)
    def cancel_generation(task_id: str, api_key: ApiKey = Depends(api_auth), session: Session = Depends(get_session)):
        task = cancel_task(session, api_key, task_id)
        return _task_status_response(task)

    @router.get("/v1/video-generations/{task_id}/result", response_model=TaskResultResponse)
    def get_generation_result(
        task_id: str,
        request: Request,
        api_key: ApiKey = Depends(api_auth),
        session: Session = Depends(get_session),
    ):
        task = get_task_for_api_key(session, api_key, task_id)
        if task.status != "succeeded":
            raise api_error(409, "TASK_RESULT_NOT_READY", "Task result is not ready")
        assets = session.scalars(select(Asset).where(Asset.task_id == task.id, Asset.kind == "video")).all()
        outputs = [
            {
                "asset_id": asset.id,
                "kind": asset.kind,
                "download_url": str(request.url_for("get_asset_content", asset_id=asset.id)),
                "content_type": asset.content_type,
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            }
            for asset in assets
        ]
        return TaskResultResponse(task_id=task.id, status=task.status, outputs=outputs)

    @router.post("/internal/dispatch/run-once")
    def internal_run_once(
        _: None = Depends(admin_auth),
        session: Session = Depends(get_session),
    ):
        outcome = dispatch_next(session, executor, state.storage)
        if not outcome.attempt:
            return {"dispatched": False, "reason": outcome.reason}
        return {
            "dispatched": outcome.dispatched,
            "reason": outcome.reason,
            "attempt_id": outcome.attempt.id,
            "task_id": outcome.attempt.task_id,
            "worker_id": outcome.worker_id,
        }

    @router.post("/internal/dispatch/complete-running")
    def internal_complete_running(
        _: None = Depends(admin_auth),
        session: Session = Depends(get_session),
    ):
        task = complete_running(session, state.storage, executor)
        if not task:
            return {"completed": False}
        return {"completed": True, "task_id": task.id, "status": task.status, "attempt_count": task.attempt_count}

    @router.post("/internal/workers/register")
    def internal_register_worker(
        payload: WorkerRegister,
        _: None = Depends(worker_auth),
        session: Session = Depends(get_session),
    ):
        worker = register_worker(session, payload)
        return serialize_worker(worker)

    @router.post("/internal/workers/{worker_id}/heartbeat")
    def internal_worker_heartbeat(
        worker_id: str,
        payload: WorkerHeartbeat,
        _: None = Depends(worker_auth),
        session: Session = Depends(get_session),
    ):
        worker = heartbeat_worker(session, worker_id, payload)
        return serialize_worker(worker)

    @router.post("/internal/attempts/{attempt_id}/events")
    def internal_worker_attempt_event(
        attempt_id: str,
        payload: WorkerAttemptEvent,
        _: None = Depends(worker_auth),
        session: Session = Depends(get_session),
    ):
        task = apply_worker_attempt_event(session, state.storage, attempt_id, payload)
        return _serialize_task(task)

    @router.get("/admin", response_class=HTMLResponse)
    def admin_home(_: None = Depends(admin_auth), session: Session = Depends(get_session)):
        tasks = session.scalars(select(VideoTask).order_by(VideoTask.created_at.desc())).all()
        rows = "".join(
            f"<tr><td>{task.id}</td><td>{task.mode}</td><td>{task.status}</td><td>{task.attempt_count}</td><td>{task.error_code or ''}</td></tr>"
            for task in tasks
        )
        return f"""
        <html><body>
        <h1>LTX Phase 1 Admin</h1>
        <p>Executor: {executor.executor_type}</p>
        <table>
        <thead><tr><th>Task</th><th>Mode</th><th>Status</th><th>Attempts</th><th>Error</th></tr></thead>
        <tbody>{rows}</tbody>
        </table>
        </body></html>
        """

    @router.get("/admin/tasks")
    def admin_tasks(
        _: None = Depends(admin_auth),
        session: Session = Depends(get_session),
        status: str | None = None,
        mode: str | None = None,
        profile: str | None = None,
        error_code: str | None = None,
    ):
        query = select(VideoTask).order_by(VideoTask.created_at.desc())
        if status:
            query = query.where(VideoTask.status == status)
        if mode:
            query = query.where(VideoTask.mode == mode)
        if profile:
            query = query.where(VideoTask.profile == profile)
        if error_code:
            query = query.where(VideoTask.error_code == error_code)
        return [_serialize_task(task) for task in session.scalars(query).all()]

    @router.post("/admin/tasks/{task_id}/retry")
    def admin_retry_task(task_id: str, _: None = Depends(admin_auth), session: Session = Depends(get_session)):
        return _serialize_task(manual_retry(session, task_id))

    @router.get("/admin/workflow-templates")
    def admin_workflows(_: None = Depends(admin_auth), session: Session = Depends(get_session)):
        templates = session.scalars(select(WorkflowTemplate)).all()
        versions = session.scalars(select(WorkflowVersion)).all()
        profiles = session.scalars(select(WorkflowProfile)).all()
        return {
            "templates": [
                {"id": item.id, "mode": item.mode, "name": item.name, "status": item.status}
                for item in templates
            ],
            "versions": [
                {"id": item.id, "template_id": item.template_id, "version": item.version, "status": item.status}
                for item in versions
            ],
            "profiles": [
                {
                    "id": item.id,
                    "workflow_version_id": item.workflow_version_id,
                    "profile": item.profile,
                    "estimated_gpu_seconds": item.estimated_gpu_seconds,
                    "parameter_schema": item.parameter_schema,
                }
                for item in profiles
            ],
        }

    @router.post("/admin/workflow-versions")
    def admin_create_workflow_version(
        payload: dict = Body(...),
        _: None = Depends(admin_auth),
        session: Session = Depends(get_session),
    ):
        version = create_workflow_version(
            session,
            payload["template_id"],
            payload.get("source_workflow_json", {}),
            payload.get("api_workflow_json", {}),
        )
        return {"id": version.id, "status": version.status, "version": version.version}

    @router.post("/admin/workflow-versions/{version_id}/test")
    def admin_test_workflow(version_id: str, _: None = Depends(admin_auth), session: Session = Depends(get_session)):
        version = set_workflow_status(session, version_id, "testing")
        return {"id": version.id, "status": version.status}

    @router.post("/admin/workflow-versions/{version_id}/publish")
    def admin_publish_workflow(version_id: str, _: None = Depends(admin_auth), session: Session = Depends(get_session)):
        version = set_workflow_status(session, version_id, "published")
        return {"id": version.id, "status": version.status}

    @router.post("/admin/workflow-versions/{version_id}/rollback")
    def admin_rollback_workflow(version_id: str, _: None = Depends(admin_auth), session: Session = Depends(get_session)):
        version = rollback_workflow(session, version_id)
        return {"id": version.id, "status": version.status}

    @router.get("/admin/workers")
    def admin_workers(_: None = Depends(admin_auth), session: Session = Depends(get_session)):
        workers = list_workers(session)
        phase = "phase-2-worker-registry" if workers else "phase-1-control"
        return {
            "phase": phase,
            "executor": executor.health(),
            "workers": [serialize_worker(worker) for worker in workers],
        }

    @router.get("/admin/usage")
    def admin_usage(_: None = Depends(admin_auth), session: Session = Depends(get_session)):
        return usage_summary(session)

    return router


def _task_status_response(task: VideoTask) -> TaskStatusResponse:
    return TaskStatusResponse(
        task_id=task.id,
        status=task.status,
        progress=Progress(stage=task.progress_stage, percent=task.progress_percent),
        attempt_count=task.attempt_count,
        error=task.error_code,
        created_at=task.created_at.isoformat() if task.created_at else None,
        updated_at=task.updated_at.isoformat() if task.updated_at else None,
    )


def _serialize_task(task: VideoTask) -> dict:
    return {
        "task_id": task.id,
        "mode": task.mode,
        "status": task.status,
        "profile": task.profile,
        "attempt_count": task.attempt_count,
        "error_code": task.error_code,
        "progress": {"stage": task.progress_stage, "percent": task.progress_percent},
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }
