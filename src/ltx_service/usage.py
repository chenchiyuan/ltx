from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .ids import new_id
from .models import UsageLedger, VideoTask, WorkflowProfile


def record_usage(
    session: Session,
    task: VideoTask,
    result: str,
    actual_runtime_seconds: int | None,
    actual_gpu_seconds: int | None = None,
) -> UsageLedger:
    profile = session.scalar(
        select(WorkflowProfile).where(
            WorkflowProfile.workflow_version_id == task.workflow_version_id,
            WorkflowProfile.profile == task.profile,
        )
    )
    estimated = profile.estimated_gpu_seconds if profile else 0
    entry = UsageLedger(
        id=new_id("usg"),
        api_key_id=task.api_key_id,
        task_id=task.id,
        event_type="task_completed",
        profile=task.profile,
        estimated_gpu_seconds=estimated,
        actual_gpu_seconds=actual_gpu_seconds,
        actual_runtime_seconds=actual_runtime_seconds,
        attempt_count=task.attempt_count,
        result=result,
    )
    session.add(entry)
    return entry


def summarize_usage_by_api_key(session: Session) -> list[dict]:
    rows = session.scalars(select(UsageLedger)).all()
    summaries: dict[str, dict] = defaultdict(
        lambda: {
            "api_key_id": "",
            "task_count": 0,
            "succeeded_count": 0,
            "failed_count": 0,
            "attempt_count": 0,
            "estimated_gpu_seconds": 0,
            "actual_gpu_seconds": 0,
            "actual_runtime_seconds": 0,
        }
    )
    for row in rows:
        summary = summaries[row.api_key_id]
        summary["api_key_id"] = row.api_key_id
        summary["task_count"] += 1
        if row.result == "succeeded":
            summary["succeeded_count"] += 1
        if row.result == "failed":
            summary["failed_count"] += 1
        summary["attempt_count"] += row.attempt_count
        summary["estimated_gpu_seconds"] += row.estimated_gpu_seconds
        summary["actual_gpu_seconds"] += row.actual_gpu_seconds or 0
        summary["actual_runtime_seconds"] += row.actual_runtime_seconds or 0
    return sorted(summaries.values(), key=lambda item: item["api_key_id"])
