from __future__ import annotations

from dataclasses import dataclass
import json
import urllib.error
import urllib.request
from typing import Any

from .models import GpuWorker, TaskAttempt, VideoTask


@dataclass(frozen=True)
class ExecutorResult:
    status: str
    error_class: str | None = None
    error_code: str | None = None
    output_bytes: bytes | None = None
    output_content_type: str = "video/mp4"
    runtime_seconds: int = 1


@dataclass(frozen=True)
class AssignmentResult:
    status: str
    error_class: str | None = None
    error_code: str | None = None


class ExecutorAdapter:
    executor_type = "base"

    def execute(self, task: VideoTask, attempt: TaskAttempt) -> ExecutorResult:
        raise NotImplementedError

    def assign(
        self,
        task: VideoTask,
        attempt: TaskAttempt,
        worker: GpuWorker,
        payload: dict[str, Any] | None = None,
    ) -> AssignmentResult:
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


class GpuWorkerExecutor(ExecutorAdapter):
    executor_type = "gpu-worker"

    def execute(self, task: VideoTask, attempt: TaskAttempt) -> ExecutorResult:
        return ExecutorResult(status="failed", error_class="worker_crash", error_code="GPU_WORKER_ASYNC_ONLY")

    def assign(
        self,
        task: VideoTask,
        attempt: TaskAttempt,
        worker: GpuWorker,
        payload: dict[str, Any] | None = None,
    ) -> AssignmentResult:
        prompt = str(task.request_params.get("prompt", "")).upper()
        if "ASSIGN_TRANSIENT" in prompt:
            return AssignmentResult(status="failed", error_class="transient", error_code="COMFYUI_PROMPT_FAILED")
        if "ASSIGN_INVALID" in prompt:
            return AssignmentResult(status="failed", error_class="invalid_input", error_code="REQUEST_INVALID_PARAMETER")
        if "ASSIGN_WORKER_CRASH" in prompt:
            return AssignmentResult(status="failed", error_class="worker_crash", error_code="WORKER_CRASH")
        assign_url = (worker.capabilities or {}).get("assign_url")
        if not assign_url:
            return AssignmentResult(status="accepted")
        try:
            request = urllib.request.Request(
                assign_url,
                data=json.dumps(payload or {}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                response_payload = json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            return _assignment_error_from_http(exc)
        except (OSError, json.JSONDecodeError, urllib.error.URLError):
            return AssignmentResult(status="failed", error_class="transient", error_code="WORKER_ASSIGN_UNAVAILABLE")
        if response_payload.get("status") == "accepted":
            return AssignmentResult(status="accepted")
        return AssignmentResult(
            status="failed",
            error_class=response_payload.get("error_class") or "transient",
            error_code=response_payload.get("error_code") or "WORKER_ASSIGN_FAILED",
        )

    def health(self) -> dict:
        return {"executor_type": self.executor_type, "healthy": True, "mode": "async-assignment"}


def build_executor(backend: str) -> ExecutorAdapter:
    if backend == "mock-local":
        return MockLocalExecutor()
    if backend == "gpu-worker":
        return GpuWorkerExecutor()
    raise RuntimeError(f"Unsupported executor backend: {backend}")


def _assignment_error_from_http(exc: urllib.error.HTTPError) -> AssignmentResult:
    try:
        payload = json.loads(exc.read().decode("utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        payload = {}
    return AssignmentResult(
        status="failed",
        error_class=payload.get("error_class") or ("transient" if exc.code >= 500 else "invalid_input"),
        error_code=payload.get("error_code") or f"WORKER_ASSIGN_HTTP_{exc.code}",
    )
