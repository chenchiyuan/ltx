from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .ids import new_id
from .models import ApiKey, WorkflowProfile, WorkflowTemplate, WorkflowVersion
from .security import hash_api_key


def seed_defaults(session: Session, bootstrap_api_key: str) -> None:
    _seed_api_key(session, bootstrap_api_key)
    _seed_workflows(session)
    session.commit()


def _seed_api_key(session: Session, bootstrap_api_key: str) -> None:
    key_hash = hash_api_key(bootstrap_api_key)
    existing = session.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash))
    if existing:
        return
    session.add(
        ApiKey(
            id=new_id("key"),
            key_hash=key_hash,
            name="Bootstrap API Key",
            status="active",
        )
    )


def _seed_workflows(session: Session) -> None:
    for mode, name in [
        ("text_to_video", "LTX Text to Video"),
        ("image_to_video", "LTX Image to Video"),
    ]:
        existing = session.scalar(select(WorkflowTemplate).where(WorkflowTemplate.mode == mode))
        if existing:
            version = session.scalar(
                select(WorkflowVersion)
                .where(WorkflowVersion.template_id == existing.id, WorkflowVersion.status == "published")
                .order_by(WorkflowVersion.version.desc())
            )
            if version:
                _ensure_default_profiles(session, version.id)
            continue
        template = WorkflowTemplate(id=new_id("wft"), mode=mode, name=name, status="active")
        version = WorkflowVersion(
            id=new_id("wfv"),
            template_id=template.id,
            version=1,
            status="published",
            source_workflow_json={"template": mode, "format": "source", "phase": "control-mvp"},
            api_workflow_json={"template": mode, "format": "api", "phase": "control-mvp"},
        )
        session.add(template)
        session.add(version)
        session.flush()
        _ensure_default_profiles(session, version.id)


def _ensure_default_profiles(session: Session, workflow_version_id: str) -> None:
    existing_profiles = set(
        session.scalars(
            select(WorkflowProfile.profile).where(WorkflowProfile.workflow_version_id == workflow_version_id)
        ).all()
    )
    defaults = [
        ("fast", 180, 1),
        ("ultra", 360, 2),
        ("vip", 720, 4),
        ("quality", 360, 1),
    ]
    for profile, estimated_gpu_seconds, gpu_count in defaults:
        if profile in existing_profiles:
            continue
        session.add(
            WorkflowProfile(
                id=new_id("wfp"),
                workflow_version_id=workflow_version_id,
                profile=profile,
                estimated_gpu_seconds=estimated_gpu_seconds,
                parameter_schema={
                    "duration_seconds": {"min": 1, "max": 60},
                    "aspect_ratio": ["16:9", "9:16", "1:1", "4:3", "3:4"],
                    "gpu_count": gpu_count,
                },
            )
        )
