from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .errors import api_error
from .ids import new_id
from .models import WorkflowProfile, WorkflowTemplate, WorkflowVersion


def get_published_workflow(session: Session, mode: str, profile: str) -> tuple[WorkflowVersion, WorkflowProfile]:
    template = session.scalar(select(WorkflowTemplate).where(WorkflowTemplate.mode == mode, WorkflowTemplate.status == "active"))
    if not template:
        raise api_error(422, "REQUEST_INVALID_PARAMETER", f"No workflow template for mode: {mode}")
    version = session.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.template_id == template.id,
            WorkflowVersion.status == "published",
        )
    )
    if not version:
        raise api_error(422, "REQUEST_INVALID_PARAMETER", f"No published workflow for mode: {mode}")
    workflow_profile = session.scalar(
        select(WorkflowProfile).where(
            WorkflowProfile.workflow_version_id == version.id,
            WorkflowProfile.profile == profile,
        )
    )
    if not workflow_profile:
        raise api_error(422, "REQUEST_INVALID_PARAMETER", f"No workflow profile: {profile}")
    return version, workflow_profile


def create_workflow_version(session: Session, template_id: str, source_json: dict, api_json: dict) -> WorkflowVersion:
    template = session.get(WorkflowTemplate, template_id)
    if not template:
        raise api_error(404, "WORKFLOW_TEMPLATE_NOT_FOUND", "Workflow template not found")
    latest = session.scalars(
        select(WorkflowVersion).where(WorkflowVersion.template_id == template_id).order_by(WorkflowVersion.version.desc())
    ).first()
    version_no = (latest.version if latest else 0) + 1
    version = WorkflowVersion(
        id=new_id("wfv"),
        template_id=template_id,
        version=version_no,
        status="draft",
        source_workflow_json=source_json,
        api_workflow_json=api_json,
    )
    session.add(version)
    if latest:
        profiles = session.scalars(select(WorkflowProfile).where(WorkflowProfile.workflow_version_id == latest.id)).all()
        session.add_all(
            WorkflowProfile(
                id=new_id("wfp"),
                workflow_version_id=version.id,
                profile=profile.profile,
                estimated_gpu_seconds=profile.estimated_gpu_seconds,
                parameter_schema=profile.parameter_schema,
            )
            for profile in profiles
        )
    session.commit()
    session.refresh(version)
    return version


def set_workflow_status(session: Session, version_id: str, status: str) -> WorkflowVersion:
    version = session.get(WorkflowVersion, version_id)
    if not version:
        raise api_error(404, "WORKFLOW_VERSION_NOT_FOUND", "Workflow version not found")
    if status == "published":
        published = session.scalars(
            select(WorkflowVersion).where(
                WorkflowVersion.template_id == version.template_id,
                WorkflowVersion.status == "published",
            )
        ).all()
        for item in published:
            item.status = "archived"
    version.status = status
    session.commit()
    session.refresh(version)
    return version


def rollback_workflow(session: Session, version_id: str) -> WorkflowVersion:
    target = session.get(WorkflowVersion, version_id)
    if not target:
        raise api_error(404, "WORKFLOW_VERSION_NOT_FOUND", "Workflow version not found")
    current = session.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.template_id == target.template_id,
            WorkflowVersion.status == "published",
        )
    )
    if current:
        current.status = "rolled_back"
        current.rollback_from_version = target.id
    target.status = "published"
    session.commit()
    session.refresh(target)
    return target
