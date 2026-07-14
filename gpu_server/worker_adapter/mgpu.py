from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any


def frame_count_for_duration(duration_seconds: int, frame_rate: float) -> int:
    raw_frames = max(8, int(duration_seconds * frame_rate))
    return (raw_frames // 8) * 8 + 1


def dimensions_for_aspect_ratio(aspect_ratio: str) -> tuple[int, int]:
    presets = {
        "16:9": (768, 512),
        "9:16": (512, 768),
        "1:1": (512, 512),
        "4:3": (768, 576),
        "3:4": (576, 768),
    }
    return presets.get(aspect_ratio, presets["16:9"])


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    return int(value)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _required_path(env_name: str, default: str) -> str:
    path = os.getenv(env_name, default)
    if not Path(path).exists():
        raise ValueError(f"{env_name} path not found: {path}")
    return path


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

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError(f"LTX MGPU completed without output: {output_path}")
        return output_path.read_bytes()

    def shutdown(self) -> None:
        if self._controller is not None:
            self._controller.shutdown(graceful_timeout=60.0)
            self._controller = None

    def _ensure_controller(self):
        if self._controller is not None and self._controller.is_alive:
            return self._controller

        pipeline = os.getenv("MGPU_PIPELINE", "two_stage").strip().lower().replace("-", "_")
        if pipeline in {"distilled", "distilled_single_stage"}:
            return self._start_distilled_controller()
        if pipeline not in {"two_stage", "ti2vid_two_stages"}:
            raise ValueError(f"Unsupported MGPU_PIPELINE: {pipeline}")
        return self._start_two_stage_controller()

    def _start_two_stage_controller(self):
        from ltx_pipelines.multigpu.controller import MGPUController
        from ltx_pipelines.ti2vid_two_stages_mgpu import TI2VidTwoStagesRunner
        import torch

        self._vae_queue = torch.multiprocessing.get_context("spawn").SimpleQueue()
        controller = MGPUController(TI2VidTwoStagesRunner)
        controller.start(
            timeout=_env_int("MGPU_START_TIMEOUT_SECONDS", 3600),
            checkpoint_path=_required_path(
                "MGPU_CHECKPOINT_PATH",
                "/opt/ltx/models/checkpoints/ltx-2.3-22b-dev.safetensors",
            ),
            gemma_root=_required_path("MGPU_GEMMA_ROOT", "/opt/ltx/models/gemma-3-12b-local"),
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

    def _start_distilled_controller(self):
        from ltx_pipelines.multigpu.controller import MGPUController
        import torch

        from .distilled_mgpu import FixedDistilledRunner, QuantizationBuilder

        checkpoint_path = _required_path(
            "MGPU_DISTILLED_CHECKPOINT_PATH",
            "/opt/ltx/models/checkpoints/ltx-2.3-22b-distilled-fp8.safetensors",
        )
        self._vae_queue = torch.multiprocessing.get_context("spawn").SimpleQueue()
        controller = MGPUController(FixedDistilledRunner)
        controller.start(
            timeout=_env_int("MGPU_START_TIMEOUT_SECONDS", 3600),
            distilled_checkpoint_path=checkpoint_path,
            gemma_root=_required_path("MGPU_GEMMA_ROOT", "/opt/ltx/models/gemma-3-12b-local"),
            spatial_upsampler_path=_required_path(
                "MGPU_SPATIAL_UPSAMPLER_PATH",
                "/opt/ltx/models/upscalers/ltx-2.3-spatial-upscaler-x2-1.1.safetensors",
            ),
            vae_queue=self._vae_queue,
            quantization=QuantizationBuilder(os.getenv("MGPU_QUANTIZATION", "fp8-scaled-mm"), checkpoint_path),
            offload_mode=os.getenv("MGPU_OFFLOAD_MODE", "none"),
            no_lora_swap=_env_bool("MGPU_NO_LORA_SWAP", True),
            no_audio=_env_bool("MGPU_NO_AUDIO", True),
            vae_overlap=_env_int("MGPU_VAE_OVERLAP", 4),
            distributed_vae=_env_bool("MGPU_DISTRIBUTED_VAE", False),
        )
        self._controller = controller
        return controller

    def _prepare_images(self, payload: dict[str, Any], attempt_id: str) -> list[Any]:
        input_asset = payload.get("input_asset")
        if not input_asset:
            return []

        from ltx_pipelines.utils.args import ImageConditioningInput

        input_dir = Path(os.getenv("MGPU_INPUT_DIR", "/tmp/ltx-mgpu-inputs"))
        input_dir.mkdir(parents=True, exist_ok=True)
        suffix = _suffix_for_content_type(input_asset.get("content_type") or "")
        image_path = input_dir / f"{attempt_id}_input{suffix}"
        with tempfile.NamedTemporaryFile(dir=input_dir, delete=False) as temp_file:
            temp_file.write(self.storage.read_bytes(input_asset["storage_uri"]))
            temp_name = temp_file.name
        shutil.move(temp_name, image_path)
        return [ImageConditioningInput(str(image_path), 0, float(os.getenv("MGPU_IMAGE_STRENGTH", "0.8")))]

    def _default_video_guider_params(self):
        from ltx_pipelines.utils.constants import LTX_2_3_PARAMS

        return LTX_2_3_PARAMS.video_guider_params

    def _default_audio_guider_params(self):
        from ltx_pipelines.utils.constants import LTX_2_3_PARAMS

        return LTX_2_3_PARAMS.audio_guider_params


def _suffix_for_content_type(content_type: str) -> str:
    if content_type == "image/png":
        return ".png"
    if content_type in {"image/jpeg", "image/jpg"}:
        return ".jpg"
    return ".image"
