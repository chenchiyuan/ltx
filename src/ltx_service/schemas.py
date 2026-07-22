from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class UploadCreate(BaseModel):
    filename: str
    content_type: str
    size_bytes: int = Field(ge=0)


class UploadCreated(BaseModel):
    asset_id: str
    upload_url: str
    expires_at: str


class ImageCondition(BaseModel):
    asset_id: str = Field(min_length=1)
    position: str | None = None
    frame_idx: int | None = Field(default=None, ge=0)
    strength: float = Field(default=0.8, ge=0, le=1)
    crf: int = Field(default=29, ge=0, le=100)

    @model_validator(mode="after")
    def validate_frame_location(self):
        if (self.position is None) == (self.frame_idx is None):
            raise ValueError("exactly one of position or frame_idx is required")
        if self.position is None:
            return self

        position = self.position.strip().lower()
        if position not in {"start", "end"}:
            match = re.fullmatch(r"(\d+(?:\.\d+)?)%", position)
            if not match or float(match.group(1)) > 100:
                raise ValueError("position must be start, end, or a percentage from 0% to 100%")
        self.position = position
        return self


class VideoGenerationCreate(BaseModel):
    mode: Literal["text_to_video", "image_to_video"]
    prompt: str = Field(min_length=1)
    negative_prompt: str | None = None
    image_asset_id: str | None = None
    image_conditions: list[ImageCondition] = Field(default_factory=list, max_length=4)
    profile: Literal["fast", "ultra", "vip", "quality"] = "vip"
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


class WorkerRegister(BaseModel):
    node_name: str = Field(min_length=1)
    worker_name: str = Field(min_length=1)
    gpu_index: int = Field(ge=0)
    worker_slot: int = Field(ge=0)
    status: str = "idle"
    queue_depth: int = Field(default=0, ge=0)
    capabilities: dict = Field(default_factory=dict)
    metrics_url: str | None = None


class WorkerHeartbeat(BaseModel):
    status: str
    queue_depth: int = Field(ge=0)
    capabilities: dict | None = None
    current_attempt_id: str | None = None
    metrics_url: str | None = None


class WorkerAttemptEvent(BaseModel):
    status: Literal["progress", "succeeded", "failed"]
    progress_stage: str | None = None
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    output_storage_uri: str | None = None
    output_content_type: str = "video/mp4"
    output_size_bytes: int | None = Field(default=None, ge=0)
    error_class: str | None = None
    error_code: str | None = None
    runtime_seconds: int | None = Field(default=None, ge=0)
