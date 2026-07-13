from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class UploadCreate(BaseModel):
    filename: str
    content_type: str
    size_bytes: int = Field(ge=0)


class UploadCreated(BaseModel):
    asset_id: str
    upload_url: str
    expires_at: str


class VideoGenerationCreate(BaseModel):
    mode: Literal["text_to_video", "image_to_video"]
    prompt: str = Field(min_length=1)
    negative_prompt: str | None = None
    image_asset_id: str | None = None
    profile: Literal["fast", "quality"] = "fast"
    duration_seconds: int = Field(default=5, ge=1, le=60)
    aspect_ratio: str = "16:9"
    seed: int | None = None


class VideoGenerationCreated(BaseModel):
    task_id: str
    status: str
    profile: str
    estimated_gpu_seconds: int
    created_at: str | None


class Progress(BaseModel):
    stage: str | None
    percent: int


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: Progress
    attempt_count: int
    error: str | None
    created_at: str | None
    updated_at: str | None


class ResultAsset(BaseModel):
    asset_id: str
    kind: str
    download_url: str
    content_type: str
    expires_at: str


class TaskResultResponse(BaseModel):
    task_id: str
    status: str
    outputs: list[ResultAsset]
