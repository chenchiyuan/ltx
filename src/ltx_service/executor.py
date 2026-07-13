from __future__ import annotations

from dataclasses import dataclass

from .models import TaskAttempt, VideoTask


@dataclass(frozen=True)
class ExecutorResult:
    status: str
    error_class: str | None = None
    error_code: str | None = None
    output_bytes: bytes | None = None
    output_content_type: str = "video/mp4"
    runtime_seconds: int = 1


class ExecutorAdapter:
    executor_type = "base"

    def execute(self, task: VideoTask, attempt: TaskAttempt) -> ExecutorResult:
        raise NotImplementedError

    def health(self) -> dict:
        return {"executor_type": self.executor_type, "healthy": True}


class MockLocalExecutor(ExecutorAdapter):
    executor_type = "mock-local"

    def execute(self, task: VideoTask, attempt: TaskAttempt) -> ExecutorResult:
        prompt = str(task.request_params.get("prompt", "")).upper()
        if "INVALID_INPUT" in prompt:
            return ExecutorResult(status="failed", error_class="invalid_input", error_code="REQUEST_INVALID_PARAMETER")
        if "TRANSIENT_ONCE" in prompt and attempt.attempt_no == 1:
            return ExecutorResult(status="failed", error_class="transient", error_code="COMFYUI_PROMPT_FAILED")
        if "WORKER_CRASH" in prompt and attempt.attempt_no == 1:
            return ExecutorResult(status="failed", error_class="worker_crash", error_code="WORKER_CRASH")
        if "EXECUTOR_UNAVAILABLE" in prompt:
            return ExecutorResult(status="failed", error_class="transient", error_code="EXECUTOR_UNAVAILABLE")
        data = (
            f"mock video\n"
            f"task_id={task.id}\n"
            f"mode={task.mode}\n"
            f"profile={task.profile}\n"
            f"attempt={attempt.attempt_no}\n"
        ).encode("utf-8")
        return ExecutorResult(status="succeeded", output_bytes=data, runtime_seconds=1)
