from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    return int(value)


def post_json(url: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Worker-Token": token},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode())


def get_url(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            response.read()
            return 200 <= response.status < 500
    except Exception:
        return False


def capabilities(gpu_index: int) -> dict[str, Any]:
    return {
        "modes": ["text_to_video", "image_to_video"],
        "profiles": ["fast"],
        "model": "ltx-2.3",
        "execution": "comfyui",
        "gpu_index": gpu_index,
    }


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
    return subprocess.Popen(command, cwd=comfyui_dir, text=True)


def main() -> None:
    control_plane_url = os.getenv("CONTROL_PLANE_URL", "http://control-plane:8000").rstrip("/")
    worker_token = os.environ["WORKER_TOKEN"]
    node_name = os.getenv("NODE_NAME", "ltx-gpu-001")
    gpu_index = env_int("GPU_INDEX", 0)
    worker_slot = env_int("WORKER_SLOT", gpu_index)
    worker_name = os.getenv("WORKER_NAME", f"ltx-worker-{gpu_index}")
    status = os.getenv("WORKER_STATUS", "unhealthy")
    not_ready_reason = os.getenv("WORKER_NOT_READY_REASON", "T204_ADAPTER_SKELETON")
    heartbeat_interval = env_int("HEARTBEAT_INTERVAL_SECONDS", 15)
    comfyui_url = f"http://{os.getenv('COMFYUI_HOST', '127.0.0.1')}:{os.getenv('COMFYUI_PORT', '8188')}"

    stop = False

    def handle_signal(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    comfyui = start_comfyui()

    worker_capabilities = capabilities(gpu_index)
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
        heartbeat_status = status
        heartbeat_capabilities = dict(worker_capabilities)
        heartbeat_capabilities["comfyui_healthy"] = comfyui_healthy
        if status != "idle" and not comfyui_healthy:
            heartbeat_capabilities["not_ready_reason"] = "COMFYUI_NOT_READY"

        payload = {
            "status": heartbeat_status,
            "queue_depth": 0,
            "capabilities": heartbeat_capabilities,
            "current_attempt_id": None,
            "metrics_url": None,
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


if __name__ == "__main__":
    main()
