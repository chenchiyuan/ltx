from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .errors import api_error
from .ids import new_id
from .models import GpuNode, GpuWorker
from .schemas import WorkerHeartbeat, WorkerRegister

HEARTBEAT_TIMEOUT_SECONDS = 600
ACTIVE_WORKER_STATUSES = {"starting", "idle", "busy", "draining"}


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def register_worker(session: Session, payload: WorkerRegister) -> GpuWorker:
    now = utc_now()
    node = session.scalar(select(GpuNode).where(GpuNode.node_name == payload.node_name))
    if not node:
        node = GpuNode(
            id=new_id("gnd"),
            node_name=payload.node_name,
            status="active",
            gpu_count=payload.gpu_index + 1,
        )
        session.add(node)
        session.flush()
    else:
        node.status = "active"
        node.gpu_count = max(node.gpu_count, payload.gpu_index + 1)

    worker = session.scalar(select(GpuWorker).where(GpuWorker.worker_name == payload.worker_name))
    if not worker:
        worker = GpuWorker(
            id=new_id("wrk"),
            node_id=node.id,
            worker_name=payload.worker_name,
            gpu_index=payload.gpu_index,
            worker_slot=payload.worker_slot,
            status=payload.status,
            capabilities=payload.capabilities,
            queue_depth=payload.queue_depth,
            metrics_url=payload.metrics_url,
            last_heartbeat_at=now,
        )
        session.add(worker)
    else:
        worker.node_id = node.id
        worker.gpu_index = payload.gpu_index
        worker.worker_slot = payload.worker_slot
        worker.status = payload.status
        worker.capabilities = payload.capabilities
        worker.queue_depth = payload.queue_depth
        worker.current_attempt_id = None
        worker.metrics_url = payload.metrics_url
        worker.last_heartbeat_at = now

    session.commit()
    session.refresh(worker)
    return worker


def heartbeat_worker(session: Session, worker_id: str, payload: WorkerHeartbeat) -> GpuWorker:
    worker = session.get(GpuWorker, worker_id)
    if not worker:
        raise api_error(404, "WORKER_NOT_FOUND", "Worker not found")
    worker.status = payload.status
    worker.queue_depth = payload.queue_depth
    if payload.capabilities is not None:
        worker.capabilities = payload.capabilities
    if payload.metrics_url is not None:
        worker.metrics_url = payload.metrics_url
    worker.current_attempt_id = payload.current_attempt_id
    worker.last_heartbeat_at = utc_now()
    session.commit()
    session.refresh(worker)
    return worker


def mark_stale_workers(session: Session) -> None:
    threshold = utc_now() - timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS)
    workers = session.scalars(select(GpuWorker).where(GpuWorker.status.in_(ACTIVE_WORKER_STATUSES))).all()
    changed = False
    for worker in workers:
        if worker.last_heartbeat_at is None or worker.last_heartbeat_at < threshold:
            worker.status = "offline"
            worker.queue_depth = 0
            worker.current_attempt_id = None
            changed = True
    if changed:
        session.commit()


def list_workers(session: Session) -> list[GpuWorker]:
    mark_stale_workers(session)
    return list(session.scalars(select(GpuWorker).order_by(GpuWorker.gpu_index.asc(), GpuWorker.worker_name.asc())).all())


def list_available_workers(session: Session, mode: str | None = None, profile: str | None = None) -> list[GpuWorker]:
    workers = list_workers(session)
    available: list[GpuWorker] = []
    for worker in workers:
        if worker.status != "idle" or worker.queue_depth != 0:
            continue
        capabilities = worker.capabilities or {}
        if mode and mode not in capabilities.get("modes", []):
            continue
        if profile and profile not in capabilities.get("profiles", []):
            continue
        available.append(worker)
    return available


def serialize_worker(worker: GpuWorker) -> dict:
    now = utc_now()
    heartbeat_age = None
    if worker.last_heartbeat_at:
        heartbeat_age = max(0, int((now - worker.last_heartbeat_at).total_seconds()))
    return {
        "worker_id": worker.id,
        "node_id": worker.node_id,
        "worker_name": worker.worker_name,
        "gpu_index": worker.gpu_index,
        "worker_slot": worker.worker_slot,
        "status": worker.status,
        "capabilities": worker.capabilities,
        "queue_depth": worker.queue_depth,
        "current_attempt_id": worker.current_attempt_id,
        "metrics_url": worker.metrics_url,
        "last_heartbeat_at": worker.last_heartbeat_at.isoformat() if worker.last_heartbeat_at else None,
        "heartbeat_age_seconds": heartbeat_age,
    }
