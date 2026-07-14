from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GPU_SERVER = ROOT / "gpu_server"


def read(path: str) -> str:
    return (GPU_SERVER / path).read_text()


def read_root(path: str) -> str:
    return (ROOT / path).read_text()


def test_gpu_server_required_files_exist() -> None:
    required_paths = [
        "README.md",
        ".env.example",
        "Dockerfile",
        "mgpu.Dockerfile",
        "control.Dockerfile",
        "docker-compose.yml",
        "scripts/deploy.sh",
        "scripts/healthcheck.sh",
        "scripts/download_models.sh",
        "worker_adapter/runtime.py",
        "config/worker.yaml",
        "workflows/README.md",
    ]

    for relative_path in required_paths:
        assert (GPU_SERVER / relative_path).exists(), relative_path


def test_web_frontend_required_files_exist() -> None:
    required_paths = [
        "web_frontend/Dockerfile",
        "web_frontend/nginx.conf",
        "web_frontend/index.html",
        "web_frontend/styles.css",
        "web_frontend/app.js",
    ]

    for relative_path in required_paths:
        assert (ROOT / relative_path).exists(), relative_path


def test_env_example_contains_phase2_contract_variables() -> None:
    env_example = read(".env.example")

    for variable in [
        "CONTROL_PLANE_URL",
        "WEB_PORT",
        "DISPATCH_INTERVAL_SECONDS",
        "WORKER_COUNT",
        "WORKER_SERVICES",
        "GPU_LAYOUT",
        "MODEL_DIR",
        "STORAGE_DIR",
        "WORKER_TOKEN",
    ]:
        assert f"{variable}=" in env_example

    assert "LTX_HF_REPO=Lightricks/LTX-2.3" in env_example
    assert "GEMMA_HF_REPO=Comfy-Org/ltx-2" in env_example
    assert "GEMMA_HF_FILE=split_files/text_encoders/gemma_3_12B_it.safetensors" in env_example


def test_gpu_dockerfile_pins_upstream_refs() -> None:
    dockerfile = read("Dockerfile")

    assert re.search(r"ARG COMFYUI_REF=[0-9a-f]{40}", dockerfile)
    assert re.search(r"ARG LTXVIDEO_REF=[0-9a-f]{40}", dockerfile)
    assert re.search(r"ARG RES4LYF_REF=[0-9a-f]{40}", dockerfile)
    assert "ARG TORCH_VERSION=2.8.0+cu128" in dockerfile
    assert "ComfyUI-LTXVideo" in dockerfile
    assert "RES4LYF" in dockerfile


def test_mgpu_dockerfile_pins_official_ltx2_ref_and_builds_kernels() -> None:
    dockerfile = read("mgpu.Dockerfile")

    assert re.search(r"ARG LTX2_REF=[0-9a-f]{40}", dockerfile)
    assert "packages/ltx-pipelines" in dockerfile
    assert "packages/ltx-kernels" in dockerfile
    assert "TORCH_CUDA_ARCH_LIST=8.9" in dockerfile


def test_compose_defines_four_profile_workers_with_one_one_two_four_gpu_layout() -> None:
    compose = read("docker-compose.yml")

    expected = {
        "worker-fast-0": ('device_ids: ["0"]', 'WORKER_PROFILES: fast', 'GPU_IDS: "0"'),
        "worker-fast-1": ('device_ids: ["1"]', 'WORKER_PROFILES: fast', 'GPU_IDS: "1"'),
        "worker-ultra": ('device_ids: ["2", "3"]', 'WORKER_PROFILES: ultra', 'GPU_IDS: "2,3"'),
        "worker-vip": ('device_ids: ["4", "5", "6", "7"]', 'WORKER_PROFILES: vip', 'GPU_IDS: "4,5,6,7"'),
    }
    for service_name, snippets in expected.items():
        assert f"{service_name}:" in compose
        for snippet in snippets:
            assert snippet in compose
    assert "WORKER_EXECUTION_BACKEND: ltx_mgpu" in compose
    assert 'START_COMFYUI: "false"' in compose
    assert "dockerfile: gpu_server/mgpu.Dockerfile" in compose


def test_compose_defines_separate_web_and_dispatcher_services() -> None:
    compose = read("docker-compose.yml")

    assert "web-frontend:" in compose
    assert "dockerfile: web_frontend/Dockerfile" in compose
    assert '"${WEB_PORT:-80}:80"' in compose
    assert "dispatcher:" in compose
    assert 'command: ["python", "-m", "ltx_service.dispatcher"]' in compose
    assert "LTX_ADMIN_TOKEN: ${ADMIN_TOKEN:?ADMIN_TOKEN is required}" in compose


def test_web_frontend_proxies_api_without_backend_secrets() -> None:
    nginx = read_root("web_frontend/nginx.conf")
    app = read_root("web_frontend/app.js")
    index = read_root("web_frontend/index.html")

    assert "location /api/" in nginx
    assert "proxy_pass http://control-plane:8000" in nginx
    assert 'const API_BASE = "/api";' in app
    assert "/v1/video-generations" in app
    assert "/v1/assets/uploads" in app
    assert 'value="fast"' in index
    assert 'value="ultra"' in index
    assert 'value="vip"' in index
    assert "BOOTSTRAP_API_KEY" not in index
    assert "ADMIN_TOKEN" not in index


def test_deploy_scripts_fail_fast_on_gpu_runtime() -> None:
    deploy = read("scripts/deploy.sh")
    healthcheck = read("scripts/healthcheck.sh")

    assert "nvidia-smi" in deploy
    assert "docker run --rm --gpus" in deploy
    assert "docker compose --env-file .env up -d --build --remove-orphans" in deploy
    assert "services=(control-plane dispatcher web-frontend)" in deploy
    assert "nvidia-smi -L" in healthcheck
