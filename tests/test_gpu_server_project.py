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
        "worker_adapter/distilled_mgpu.py",
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
        "MGPU_GEMMA_HF_REPO",
        "MGPU_DISTILLED_HF_REPO",
        "LTX_SPATIAL_UPSAMPLER_FILE",
        "MGPU_DISTILLED_FILE",
        "MODEL_DIR",
        "STORAGE_DIR",
        "WORKER_TOKEN",
        "COMFYUI_EXTRA_ARGS",
    ]:
        assert f"{variable}=" in env_example

    assert "LTX_HF_REPO=Lightricks/LTX-2.3" in env_example
    assert "GEMMA_HF_REPO=Comfy-Org/ltx-2" in env_example
    assert "GEMMA_HF_FILE=split_files/text_encoders/gemma_3_12B_it.safetensors" in env_example
    assert "MGPU_GEMMA_HF_REPO=google/gemma-3-12b-it" in env_example
    assert "MGPU_DISTILLED_HF_REPO=Lightricks/LTX-2" in env_example
    assert "LTX_SPATIAL_UPSAMPLER_FILE=ltx-2.3-spatial-upscaler-x2-1.1.safetensors" in env_example
    assert "MGPU_DISTILLED_FILE=ltx-2-19b-distilled-fp8.safetensors" in env_example
    assert "ENABLE_MGPU_EXPERIMENTAL=true" in env_example
    assert "WORKER_COUNT=5" in env_example
    assert "WORKER_SERVICES=worker-fast-0,worker-fast-1,worker-fast-2,worker-fast-3,worker-vip" in env_example
    assert 'GPU_LAYOUT="fast:0;fast:1;fast:2;fast:3;vip:4,5,6,7"' in env_example
    assert "MGPU_PIPELINE=distilled" in env_example
    assert "MGPU_DISTILLED_CHECKPOINT_PATH=/fp8/ltx-2-19b-distilled-fp8.safetensors" in env_example


def test_worker_runtime_passes_configured_comfyui_extra_args() -> None:
    runtime = read("worker_adapter/runtime.py")

    assert "import shlex" in runtime
    assert 'shlex.split(os.getenv("COMFYUI_EXTRA_ARGS", ""))' in runtime


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


def test_compose_defines_stable_fast_workers_and_experimental_mgpu_workers() -> None:
    compose = read("docker-compose.yml")

    expected = {
        f"worker-fast-{gpu_index}": (
            f'device_ids: ["{gpu_index}"]',
            "WORKER_PROFILES: fast",
            f'GPU_IDS: "{gpu_index}"',
        )
        for gpu_index in range(8)
    }
    expected["worker-ultra"] = ('device_ids: ["2", "3"]', 'WORKER_PROFILES: ultra', 'GPU_IDS: "2,3"')
    expected["worker-vip"] = ('device_ids: ["4", "5", "6", "7"]', 'WORKER_PROFILES: vip', 'GPU_IDS: "4,5,6,7"')
    for service_name, snippets in expected.items():
        assert f"{service_name}:" in compose
        for snippet in snippets:
            assert snippet in compose
    assert "WORKER_EXECUTION_BACKEND: ltx_mgpu" in compose
    assert 'START_COMFYUI: "false"' in compose
    assert "MGPU_PIPELINE: ${MGPU_PIPELINE:-distilled}" in compose
    assert "MGPU_DISTILLED_CHECKPOINT_PATH: ${MGPU_DISTILLED_CHECKPOINT_PATH:-/fp8/ltx-2-19b-distilled-fp8.safetensors}" in compose
    assert "MGPU_GEMMA_ROOT: ${MGPU_GEMMA_ROOT:-/opt/ltx/models/gemma-3-12b-local}" in compose
    assert "${MGPU_DISTILLED_CACHE_DIR:-/opt/ltx/models/checkpoints}:/fp8:ro" in compose
    assert "${MGPU_GEMMA_CACHE_DIR:-/opt/ltx/models/gemma-3-12b-local}:/gemma:ro" in compose
    assert "dockerfile: gpu_server/mgpu.Dockerfile" in compose
    assert compose.count('profiles: ["workers"]') == 8
    assert compose.count('profiles: ["mgpu-experimental"]') == 2


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
    assert 'value="ultra" disabled' in index
    assert 'value="vip" disabled' not in index
    assert 'value="vip">vip · 4 GPU' in index
    assert "BOOTSTRAP_API_KEY" not in index
    assert "ADMIN_TOKEN" not in index


def test_web_frontend_supports_start_end_and_middle_reference_frames() -> None:
    app = read_root("web_frontend/app.js")
    index = read_root("web_frontend/index.html")

    for element_id in [
        "singleImageField",
        "multiReferenceField",
        "startImage",
        "endImage",
        "middleReferences",
        "addMiddleReference",
    ]:
        assert f'id="{element_id}"' in index

    assert 'data-reference-mode="single"' in index
    assert 'data-reference-mode="multi"' in index
    assert 'payload.image_conditions = imageConditions' in app
    assert "MAX_IMAGE_CONDITIONS = 4" in app
    assert 'position: "start"' in app
    assert 'position: "end"' in app
    assert 'els.profile.value = "vip"' in app


def test_deploy_scripts_fail_fast_on_gpu_runtime() -> None:
    deploy = read("scripts/deploy.sh")
    healthcheck = read("scripts/healthcheck.sh")
    download_models = read("scripts/download_models.sh")

    assert "nvidia-smi" in deploy
    assert "docker run --rm --gpus" in deploy
    assert "docker compose --env-file .env up -d --build --remove-orphans" in deploy
    assert "services=(control-plane dispatcher web-frontend)" in deploy
    assert "ENABLE_MGPU_EXPERIMENTAL" in deploy
    assert "Marked skipped worker offline" in deploy
    assert "nvidia-smi -L" in healthcheck
    assert "worker-fast-0" in download_models
    assert "worker-vip" in download_models
    assert "worker-0 download" not in download_models
    assert "MGPU_GEMMA_HF_REPO" in download_models
    assert "ltx-2.3-spatial-upscaler-x2-1.1.safetensors" in download_models
