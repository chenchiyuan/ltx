from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GPU_SERVER = ROOT / "gpu_server"


def read(path: str) -> str:
    return (GPU_SERVER / path).read_text()


def test_gpu_server_required_files_exist() -> None:
    required_paths = [
        "README.md",
        ".env.example",
        "Dockerfile",
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


def test_env_example_contains_phase2_contract_variables() -> None:
    env_example = read(".env.example")

    for variable in [
        "CONTROL_PLANE_URL",
        "WORKER_COUNT",
        "GPU_INDICES",
        "MODEL_DIR",
        "STORAGE_DIR",
        "WORKER_TOKEN",
    ]:
        assert f"{variable}=" in env_example


def test_gpu_dockerfile_pins_upstream_refs() -> None:
    dockerfile = read("Dockerfile")

    assert re.search(r"ARG COMFYUI_REF=[0-9a-f]{40}", dockerfile)
    assert re.search(r"ARG LTXVIDEO_REF=[0-9a-f]{40}", dockerfile)
    assert "ARG TORCH_VERSION=2.8.0+cu128" in dockerfile
    assert "ComfyUI-LTXVideo" in dockerfile


def test_compose_defines_eight_single_gpu_workers() -> None:
    compose = read("docker-compose.yml")

    for gpu_index in range(8):
        assert f"worker-{gpu_index}:" in compose
        assert f'GPU_INDEX: "{gpu_index}"' in compose
        assert f'device_ids: ["{gpu_index}"]' in compose


def test_deploy_scripts_fail_fast_on_gpu_runtime() -> None:
    deploy = read("scripts/deploy.sh")
    healthcheck = read("scripts/healthcheck.sh")

    assert "nvidia-smi" in deploy
    assert "docker run --rm --gpus" in deploy
    assert "docker compose --env-file .env up -d --build" in deploy
    assert "nvidia-smi -L" in healthcheck
