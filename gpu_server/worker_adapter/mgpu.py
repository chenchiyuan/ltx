from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

from .workflow_inputs import image_contract_from_payload, prepare_workflow_image_input


def frame_count_for_duration(duration_seconds: int, frame_rate: float) -> int:
    raw_frames = max(8, int(duration_seconds * frame_rate))
    return (raw_frames // 8) * 8 + 1


def dimensions_for_aspect_ratio(aspect_ratio: str) -> tuple[int, int]:
    presets = {
        "16:9": (1024, 576),
        "9:16": (576, 1024),
        "1:1": (768, 768),
        "4:3": (1024, 768),
        "3:4": (768, 1024),
    }
    return presets.get(aspect_ratio, presets["16:9"])


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    return int(value)


def _env_timedelta_seconds(name: str, default: int) -> timedelta:
    return timedelta(seconds=_env_int(name, default))


def _required_path(env_name: str, default: str) -> str:
    path = os.getenv(env_name, default)
    if not Path(path).exists():
        raise ValueError(f"{env_name} path not found: {path}")
    return path


def validate_mgpu_model_contract() -> None:
    pipeline = os.getenv("MGPU_PIPELINE", "two_stage").strip().lower().replace("-", "_")
    if pipeline not in {"two_stage", "ti2vid_two_stages"}:
        raise ValueError(f"MGPU_PIPELINE must use the official two-stage runner, got: {pipeline}")

    quantization = os.getenv("MGPU_QUANTIZATION", "fp8-cast").strip().lower()
    if quantization != "fp8-cast":
        raise ValueError(f"MGPU_QUANTIZATION must be fp8-cast for the LTX 2.3 dev checkpoint, got: {quantization}")

    required_models = {
        "MGPU_CHECKPOINT_PATH": (
            "/opt/ltx/models/checkpoints/ltx-2.3-22b-dev.safetensors",
            "ltx-2.3-22b-dev.safetensors",
        ),
        "MGPU_DISTILLED_LORA_PATH": (
            "/opt/ltx/models/loras/ltxv/ltx2/ltx-2.3-22b-distilled-lora-384-1.1.safetensors",
            "ltx-2.3-22b-distilled-lora-384-1.1.safetensors",
        ),
        "MGPU_SPATIAL_UPSAMPLER_PATH": (
            "/opt/ltx/models/upscalers/ltx-2.3-spatial-upscaler-x2-1.1.safetensors",
            "ltx-2.3-spatial-upscaler-x2-1.1.safetensors",
        ),
    }
    for env_name, (default, expected_name) in required_models.items():
        path = Path(_required_path(env_name, default))
        if path.name != expected_name:
            raise ValueError(f"{env_name} must reference {expected_name}, got: {path.name}")
        if path.stat().st_size == 0:
            raise ValueError(f"{env_name} is empty: {path}")

    gemma_root = Path(_required_path("MGPU_GEMMA_ROOT", "/opt/ltx/models/gemma-3-12b-qat"))
    config_path = gemma_root / "config.json"
    index_path = gemma_root / "model.safetensors.index.json"
    tokenizer_path = gemma_root / "tokenizer.json"
    for path in (config_path, index_path, tokenizer_path):
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"MGPU Gemma file is missing or empty: {path}")

    try:
        config = json.loads(config_path.read_text())
        weight_map = json.loads(index_path.read_text())["weight_map"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"MGPU Gemma metadata is invalid under {gemma_root}: {exc}") from exc

    if "Gemma3ForConditionalGeneration" not in config.get("architectures", []):
        raise ValueError(f"MGPU Gemma architecture is incompatible: {config.get('architectures', [])}")

    keys = set(weight_map)
    language_model_present = any(
        key.startswith(("language_model.", "model.language_model.")) for key in keys
    )
    vision_tower_present = any(key.startswith(("vision_tower.", "model.vision_tower.")) for key in keys)
    tied_language_model_head = any(key.endswith("language_model.model.embed_tokens.weight") for key in keys)
    required_weight_keys = {
        "language model": language_model_present,
        "vision tower": vision_tower_present,
        "language model head": "lm_head.weight" in keys or tied_language_model_head,
    }
    missing_keys = [name for name, present in required_weight_keys.items() if not present]
    if missing_keys:
        raise ValueError(f"Gemma weight contract is incompatible; missing: {', '.join(missing_keys)}")

    for shard_name in set(weight_map.values()):
        shard_path = gemma_root / shard_name
        if not shard_path.is_file() or shard_path.stat().st_size == 0:
            raise ValueError(f"MGPU Gemma shard is missing or empty: {shard_path}")


class LtxMgpuExecutor:
    def __init__(self, storage) -> None:
        self.storage = storage
        self._controller = None
        self._vae_queue = None

    def execute(self, payload: dict[str, Any], attempt_id: str) -> bytes:
        executor = self._ensure_controller()
        output_dir = Path(os.getenv("MGPU_OUTPUT_DIR", "/tmp/ltx-mgpu-outputs"))
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{attempt_id}.mp4"
        if output_path.exists():
            output_path.unlink()

        params = payload.get("request_params") or {}
        prompt = str(params.get("prompt") or "")
        if not prompt:
            raise ValueError("prompt is required for ltx_mgpu execution")

        frame_rate = float(params.get("frame_rate") or 24)
        duration_seconds = int(params.get("duration_seconds") or 5)
        width, height = dimensions_for_aspect_ratio(str(params.get("aspect_ratio") or "16:9"))
        seed = int(params.get("seed") or _env_int("MGPU_DEFAULT_SEED", 42))
        images = self._prepare_images(payload, attempt_id)

        try:
            stream = executor.stream(
                output_path=str(output_path),
                prompt=prompt,
                negative_prompt=str(params.get("negative_prompt") or ""),
                seed=seed,
                height=int(params.get("height") or height),
                width=int(params.get("width") or width),
                num_frames=int(params.get("num_frames") or frame_count_for_duration(duration_seconds, frame_rate)),
                frame_rate=frame_rate,
                num_inference_steps=int(params.get("num_inference_steps") or _env_int("MGPU_NUM_INFERENCE_STEPS", 8)),
                video_guider_params=self._default_video_guider_params(),
                audio_guider_params=self._default_audio_guider_params(),
                images=images,
                timeout=_env_int("MGPU_JOB_TIMEOUT_SECONDS", 7200),
            )
            try:
                for _ in stream:
                    pass
            finally:
                stream.drain()
        finally:
            self.shutdown()

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError(f"LTX MGPU completed without output: {output_path}")
        return output_path.read_bytes()

    def shutdown(self) -> None:
        if self._controller is not None:
            self._controller.shutdown(graceful_timeout=60.0)
            self._controller = None
            self._vae_queue = None

    def _ensure_controller(self):
        if self._controller is not None and self._controller.is_alive:
            return self._controller

        validate_mgpu_model_contract()
        return self._start_two_stage_controller()

    def _start_two_stage_controller(self):
        from ltx_pipelines.multigpu.controller import MGPUController
        from ltx_pipelines.ti2vid_two_stages_mgpu import TI2VidTwoStagesRunner
        import torch

        self._vae_queue = torch.multiprocessing.get_context("spawn").SimpleQueue()
        controller = MGPUController(TI2VidTwoStagesRunner)
        controller.start(
            timeout=_env_timedelta_seconds("MGPU_START_TIMEOUT_SECONDS", 3600),
            checkpoint_path=_required_path(
                "MGPU_CHECKPOINT_PATH",
                "/opt/ltx/models/checkpoints/ltx-2.3-22b-dev.safetensors",
            ),
            gemma_root=_required_path("MGPU_GEMMA_ROOT", "/opt/ltx/models/gemma-3-12b-qat"),
            spatial_upsampler_path=_required_path(
                "MGPU_SPATIAL_UPSAMPLER_PATH",
                "/opt/ltx/models/upscalers/ltx-2.3-spatial-upscaler-x2-1.1.safetensors",
            ),
            distilled_lora_path=_required_path(
                "MGPU_DISTILLED_LORA_PATH",
                "/opt/ltx/models/loras/ltxv/ltx2/ltx-2.3-22b-distilled-lora-384-1.1.safetensors",
            ),
            vae_queue=self._vae_queue,
        )
        self._controller = controller
        return controller

    def _prepare_images(self, payload: dict[str, Any], attempt_id: str) -> list[Any]:
        input_assets = payload.get("input_assets") or []
        legacy_input = not input_assets and payload.get("input_asset")
        if legacy_input:
            input_assets = [
                {
                    **legacy_input,
                    "frame_idx": 0,
                    "strength": float(os.getenv("MGPU_IMAGE_STRENGTH", "0.8")),
                    "crf": 29,
                }
            ]
        if not input_assets:
            return []

        from ltx_pipelines.utils.args import ImageConditioningInput

        input_dir = Path(os.getenv("MGPU_INPUT_DIR", "/tmp/ltx-mgpu-inputs"))
        contract = image_contract_from_payload(payload)
        images = []
        for index, input_asset in enumerate(input_assets):
            filename_stem = f"{attempt_id}_input" if legacy_input else f"{attempt_id}_input_{index}"
            image_path = prepare_workflow_image_input(
                image_bytes=self.storage.read_bytes(input_asset["storage_uri"]),
                output_dir=input_dir,
                filename_stem=filename_stem,
                contract=contract,
            )
            images.append(
                ImageConditioningInput(
                    str(image_path),
                    int(input_asset.get("frame_idx", 0)),
                    float(input_asset.get("strength", os.getenv("MGPU_IMAGE_STRENGTH", "0.8"))),
                    int(input_asset.get("crf", 29)),
                )
            )
        return images

    def _default_video_guider_params(self):
        from ltx_pipelines.utils.constants import LTX_2_3_PARAMS

        return LTX_2_3_PARAMS.video_guider_params

    def _default_audio_guider_params(self):
        from ltx_pipelines.utils.constants import LTX_2_3_PARAMS

        return LTX_2_3_PARAMS.audio_guider_params
