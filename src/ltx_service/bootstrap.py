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
        profiles = [
            WorkflowProfile(
                id=new_id("wfp"),
                workflow_version_id=version.id,
                profile="fast",
                estimated_gpu_seconds=180,
                parameter_schema={"duration_seconds": {"min": 1, "max": 10}, "aspect_ratio": ["16:9", "9:16"]},
            ),
            WorkflowProfile(
                id=new_id("wfp"),
                workflow_version_id=version.id,
                profile="quality",
                estimated_gpu_seconds=360,
                parameter_schema={"duration_seconds": {"min": 1, "max": 10}, "aspect_ratio": ["16:9", "9:16"]},
            ),
        ]
        session.add(template)
        session.add(version)
        session.add_all(profiles)
