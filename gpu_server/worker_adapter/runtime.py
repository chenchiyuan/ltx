from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .comfyui import ComfyUIClient, inject_assignment_parameters, load_workflow_api, run_prompt_and_fetch_video
from .storage import LocalSharedStorage
from .workflow_inputs import ImagePreprocessError, image_contract_from_payload, prepare_workflow_image_input


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    return int(value)


def env_csv(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if not value:
        return default
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or default


def post_json(url: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Worker-Token": token},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode())


def post_json_without_response(url: str, token: str, payload: dict[str, Any]) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Worker-Token": token},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        response.read()


def get_url(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            response.read()
            return 200 <= response.status < 500
    except Exception:
        return False


def capabilities(gpu_index: int, gpu_indices: list[int], profiles: list[str]) -> dict[str, Any]:
    return {
        "modes": ["text_to_video", "image_to_video"],
        "profiles": profiles,
        "model": "ltx-2.3",
        "execution": os.getenv("WORKER_EXECUTION_BACKEND", "comfyui"),
        "gpu_index": gpu_index,
        "gpu_indices": gpu_indices,
        "gpu_count": len(gpu_indices),
    }


class WorkerRuntime:
    def __init__(
        self,
        control_plane_url: str,
        worker_token: str,
        comfyui_url: str,
        storage_root: Path,
        workflow_path: Path,
    ):
        self.control_plane_url = control_plane_url.rstrip("/")
        self.worker_token = worker_token
        self.comfyui_url = comfyui_url.rstrip("/")
        self.storage = LocalSharedStorage(storage_root)
        self.workflow_path = workflow_path
        self.lock = threading.Lock()
        self.current_attempt_id: str | None = None
        self.last_error: str | None = None
        self.base_status = "unhealthy"
        self._ltx_mgpu_executor = None

    def accept_attempt(self, payload: dict[str, Any]) -> dict[str, str]:
        attempt_id = str(payload.get("attempt_id") or "")
        if not attempt_id:
            return {"status": "failed", "error_class": "invalid_input", "error_code": "ATTEMPT_ID_REQUIRED"}
        with self.lock:
            if self.current_attempt_id:
                return {"status": "failed", "error_class": "transient", "error_code": "WORKER_BUSY"}
            self.current_attempt_id = attempt_id
        thread = threading.Thread(target=self._run_attempt, args=(payload,), daemon=True)
        thread.start()
        return {"status": "accepted"}

    def heartbeat_status(self, base_status: str) -> tuple[str, int, str | None]:
        with self.lock:
            if self.current_attempt_id:
                return "busy", 1, self.current_attempt_id
        return base_status, 0, None

    def metrics(self) -> str:
        status, queue_depth, current_attempt_id = self.heartbeat_status(self.base_status)
        current = current_attempt_id or ""
        return (
            "# HELP ltx_worker_queue_depth Current worker queue depth\n"
            "# TYPE ltx_worker_queue_depth gauge\n"
            f"ltx_worker_queue_depth {queue_depth}\n"
            "# HELP ltx_worker_busy Worker busy state\n"
            "# TYPE ltx_worker_busy gauge\n"
            f'ltx_worker_busy{{status="{status}",current_attempt_id="{current}"}} {1 if status == "busy" else 0}\n'
        )

    def _run_attempt(self, payload: dict[str, Any]) -> None:
        attempt_id = str(payload["attempt_id"])
        started_at = time.monotonic()
        try:
            self._post_event(attempt_id, {"status": "progress", "progress_stage": "worker_received", "progress_percent": 15})
            backend = os.getenv("WORKER_EXECUTION_BACKEND", "comfyui")
            if backend == "mock":
                output = f"mock gpu worker output\nattempt_id={attempt_id}\n".encode("utf-8")
            elif backend == "ltx_mgpu":
                output = self._execute_ltx_mgpu(payload, attempt_id)
            else:
                output = self._execute_comfyui(payload, attempt_id)
            output_uri = payload["output"]["storage_uri"]
            output_size = self.storage.write_bytes(output_uri, output)
            self._post_event(
                attempt_id,
                {
                    "status": "succeeded",
                    "progress_stage": "completed",
                    "progress_percent": 100,
                    "output_storage_uri": output_uri,
                    "output_content_type": payload["output"].get("content_type", "video/mp4"),
                    "output_size_bytes": output_size,
                    "runtime_seconds": int(time.monotonic() - started_at),
                },
            )
        except Exception as exc:
            self.last_error = f"{exc.__class__.__name__}: {exc}"
            self._post_event(
                attempt_id,
                {
                    "status": "failed",
                    "progress_stage": "failed",
                    "progress_percent": 100,
                    "error_class": _classify_error(exc),
                    "error_code": _error_code(exc),
                    "runtime_seconds": int(time.monotonic() - started_at),
                },
            )
        finally:
            with self.lock:
                if self.current_attempt_id == attempt_id:
                    self.current_attempt_id = None

    def _execute_comfyui(self, payload: dict[str, Any], attempt_id: str) -> bytes:
        client = ComfyUIClient(self.comfyui_url)
        input_image_name = self._prepare_input_image(payload, attempt_id)
        prompt = load_workflow_api(self.workflow_path, client)
        prompt = inject_assignment_parameters(prompt, payload, input_image_name, f"ltx_{attempt_id}")
        self._post_event(attempt_id, {"status": "progress", "progress_stage": "comfyui_queued", "progress_percent": 25})
        return run_prompt_and_fetch_video(
            client,
            prompt,
            poll_interval_seconds=env_int("COMFYUI_POLL_INTERVAL_SECONDS", 5),
            timeout_seconds=env_int("COMFYUI_TIMEOUT_SECONDS", 3600),
        )

    def _execute_ltx_mgpu(self, payload: dict[str, Any], attempt_id: str) -> bytes:
        if self._ltx_mgpu_executor is None:
            from .mgpu import LtxMgpuExecutor

            self._ltx_mgpu_executor = LtxMgpuExecutor(self.storage)
        return self._ltx_mgpu_executor.execute(payload, attempt_id)

    def _prepare_input_image(self, payload: dict[str, Any], attempt_id: str) -> str | None:
        input_asset = payload.get("input_asset")
        if not input_asset:
            return None
        input_dir = Path(os.getenv("COMFYUI_INPUT_DIR", "/opt/comfyui/input"))
        image_path = prepare_workflow_image_input(
            image_bytes=self.storage.read_bytes(input_asset["storage_uri"]),
            output_dir=input_dir,
            filename_stem=f"{attempt_id}_input",
            contract=image_contract_from_payload(payload),
        )
        return image_path.name

    def _post_event(self, attempt_id: str, payload: dict[str, Any]) -> None:
        post_json_without_response(
            f"{self.control_plane_url}/internal/attempts/{attempt_id}/events",
            self.worker_token,
            payload,
        )


class WorkerHttpServer(ThreadingHTTPServer):
    runtime: WorkerRuntime


class WorkerRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})
            return
        if self.path == "/metrics":
            body = self.server.runtime.metrics().encode("utf-8")  # type: ignore[attr-defined]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/worker/attempts":
            self._send_json(404, {"error": "not_found"})
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send_json(400, {"status": "failed", "error_class": "invalid_input", "error_code": "INVALID_JSON"})
            return
        result = self.server.runtime.accept_attempt(payload)  # type: ignore[attr-defined]
        status = 202 if result.get("status") == "accepted" else 409
        self._send_json(status, result)

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_worker_http_server(runtime: WorkerRuntime, host: str, port: int) -> WorkerHttpServer:
    server = WorkerHttpServer((host, port), WorkerRequestHandler)
    server.runtime = runtime
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def start_comfyui() -> subprocess.Popen[str] | None:
    if os.getenv("START_COMFYUI", "true").lower() not in {"1", "true", "yes"}:
        return None
    comfyui_dir = Path(os.getenv("COMFYUI_DIR", "/opt/comfyui"))
    host = os.getenv("COMFYUI_HOST", "127.0.0.1")
    port = os.getenv("COMFYUI_PORT", "8188")
    command = [
        sys.executable,
        "main.py",
        "--listen",
        host,
        "--port",
        port,
    ]
    command.extend(shlex.split(os.getenv("COMFYUI_EXTRA_ARGS", "")))
    return subprocess.Popen(command, cwd=comfyui_dir, text=True)


def main() -> None:
    control_plane_url = os.getenv("CONTROL_PLANE_URL", "http://control-plane:8000").rstrip("/")
    worker_token = os.environ["WORKER_TOKEN"]
    node_name = os.getenv("NODE_NAME", "ltx-gpu-001")
    gpu_index = env_int("GPU_INDEX", 0)
    gpu_indices = [int(item) for item in env_csv("GPU_IDS", [str(gpu_index)])]
    worker_slot = env_int("WORKER_SLOT", gpu_index)
    worker_name = os.getenv("WORKER_NAME", f"ltx-worker-{gpu_index}")
    worker_profiles = env_csv("WORKER_PROFILES", ["fast"])
    status = os.getenv("WORKER_STATUS", "unhealthy")
    not_ready_reason = os.getenv("WORKER_NOT_READY_REASON", "T204_ADAPTER_SKELETON")
    heartbeat_interval = env_int("HEARTBEAT_INTERVAL_SECONDS", 15)
    comfyui_url = f"http://{os.getenv('COMFYUI_HOST', '127.0.0.1')}:{os.getenv('COMFYUI_PORT', '8188')}"
    worker_api_host = os.getenv("WORKER_API_HOST", "0.0.0.0")
    worker_api_port = env_int("WORKER_API_PORT", 9000)
    worker_assign_host = os.getenv("WORKER_ASSIGN_HOST", worker_name)
    storage_root = Path(os.getenv("STORAGE_DIR", "/data/ltx-storage"))
    workflow_path = Path(
        os.getenv(
            "WORKFLOW_PATH",
            "/opt/comfyui/custom_nodes/ComfyUI-LTXVideo/example_workflows/2.3/LTX-2.3_T2V_I2V_Single_Stage_Distilled_Full.json",
        )
    )

    if os.getenv("WORKER_EXECUTION_BACKEND", "comfyui") == "ltx_mgpu":
        from .mgpu import validate_mgpu_model_contract

        validate_mgpu_model_contract()

    stop = False

    def handle_signal(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    runtime = WorkerRuntime(control_plane_url, worker_token, comfyui_url, storage_root, workflow_path)
    runtime.base_status = status
    worker_server = start_worker_http_server(runtime, worker_api_host, worker_api_port)
    comfyui = start_comfyui()

    worker_capabilities = capabilities(gpu_index, gpu_indices, worker_profiles)
    worker_capabilities["assign_url"] = f"http://{worker_assign_host}:{worker_api_port}/worker/attempts"
    worker_capabilities["workflow"] = workflow_path.name
    if status != "idle":
        worker_capabilities["not_ready_reason"] = not_ready_reason

    register_payload = {
        "node_name": node_name,
        "worker_name": worker_name,
        "gpu_index": gpu_index,
        "worker_slot": worker_slot,
        "status": status,
        "queue_depth": 0,
        "capabilities": worker_capabilities,
        "metrics_url": None,
    }

    worker_id: str | None = None
    while not stop and worker_id is None:
        try:
            response = post_json(f"{control_plane_url}/internal/workers/register", worker_token, register_payload)
            worker_id = response["worker_id"]
            print(f"registered worker_id={worker_id}", flush=True)
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError) as exc:
            print(f"register failed: {exc}", flush=True)
            time.sleep(heartbeat_interval)

    while not stop:
        comfyui_healthy = get_url(f"{comfyui_url}/system_stats") if comfyui else True
        heartbeat_status, queue_depth, current_attempt_id = runtime.heartbeat_status(status)
        heartbeat_capabilities = dict(worker_capabilities)
        heartbeat_capabilities["comfyui_healthy"] = comfyui_healthy
        if runtime.last_error:
            heartbeat_capabilities["last_error"] = runtime.last_error
        if heartbeat_status != "idle" and not comfyui_healthy:
            heartbeat_capabilities["not_ready_reason"] = "COMFYUI_NOT_READY"

        payload = {
            "status": heartbeat_status,
            "queue_depth": queue_depth,
            "capabilities": heartbeat_capabilities,
            "current_attempt_id": current_attempt_id,
            "metrics_url": f"http://{worker_assign_host}:{worker_api_port}/metrics",
        }
        try:
            post_json(f"{control_plane_url}/internal/workers/{worker_id}/heartbeat", worker_token, payload)
            print(f"heartbeat status={heartbeat_status} comfyui={comfyui_healthy}", flush=True)
        except urllib.error.URLError as exc:
            print(f"heartbeat failed: {exc}", flush=True)
        time.sleep(heartbeat_interval)

    if comfyui:
        comfyui.terminate()
        try:
            comfyui.wait(timeout=20)
        except subprocess.TimeoutExpired:
            comfyui.kill()
    if runtime._ltx_mgpu_executor is not None:
        runtime._ltx_mgpu_executor.shutdown()
    worker_server.shutdown()


def _classify_error(exc: Exception) -> str:
    if isinstance(exc, ImagePreprocessError):
        return "invalid_input"
    if isinstance(exc, (TimeoutError, urllib.error.URLError, OSError)):
        return "transient"
    if isinstance(exc, ValueError):
        return "invalid_input"
    return "comfyui_prompt_failed"


def _error_code(exc: Exception) -> str:
    if isinstance(exc, ImagePreprocessError):
        return "IMAGE_PREPROCESS_FAILED"
    if isinstance(exc, TimeoutError):
        return "COMFYUI_TIMEOUT"
    if isinstance(exc, urllib.error.URLError):
        return "COMFYUI_UNAVAILABLE"
    if isinstance(exc, ValueError):
        return "REQUEST_INVALID_PARAMETER"
    if "mgpu" in exc.__class__.__name__.lower() or "LTX MGPU" in str(exc):
        return "LTX_MGPU_FAILED"
    return "COMFYUI_PROMPT_FAILED"


if __name__ == "__main__":
    main()
