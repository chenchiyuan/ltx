from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import av
import torch
import torch.distributed as dist
from ltx_core.loader.registry import StateDictRegistry
from ltx_core.model.transformer.compiling import CompilationConfig
from ltx_core.model.video_vae.tiling import TilingConfig
from ltx_core.multigpu.transformer.attention import AttentionManager
from ltx_core.quantization import QuantizationPolicy
from ltx_core.quantization.fp8_cast import build_policy as build_fp8_cast_policy
from ltx_core.tiling import DimensionTilingConfig, TileCountConfig, balanced_tile_split
from ltx_pipelines.distilled import DistilledPipeline
from ltx_pipelines.multigpu.gemma_builders import AccelerateGemmaBuilder
from ltx_pipelines.multigpu.runner import MGPURunner
from ltx_pipelines.multigpu.sp_builder import SequenceParallelBuilder
from ltx_pipelines.multigpu.vae_builders import DistributedDecoderBuilder
from ltx_pipelines.multigpu.weight_tracker import TransformerWeightTracker
from ltx_pipelines.utils.allocator_trim_strategy import AllocatorTrimStrategy
from ltx_pipelines.utils.quantization_factory import QuantizationKind
from ltx_pipelines.utils.types import OffloadMode

DEFAULT_SP_MAX_TOKENS = 32768
DRIVER_RANK = 0


class QuantizationBuilder:
    def __init__(self, kind: str, checkpoint_path: str) -> None:
        self.kind = kind
        self.checkpoint_path = checkpoint_path

    def __call__(self) -> QuantizationPolicy:
        return QuantizationKind(self.kind).to_policy(checkpoint_path=self.checkpoint_path)


class FixedDistilledRunner(MGPURunner):
    @torch.inference_mode()
    def setup(
        self,
        *,
        distilled_checkpoint_path: str,
        gemma_root: str,
        spatial_upsampler_path: str,
        vae_queue: Any,
        compilation_config: CompilationConfig | None = None,
        sp_max_tokens: int = DEFAULT_SP_MAX_TOKENS,
        quantization: Callable[[], QuantizationPolicy] | None = None,
        offload_mode: str = "none",
        no_lora_swap: bool = True,
        no_audio: bool = True,
        vae_overlap: int = 4,
        distributed_vae: bool = True,
    ) -> None:
        quantization_policy = quantization() if quantization is not None else build_fp8_cast_policy(distilled_checkpoint_path)
        registry = StateDictRegistry()
        pipeline = DistilledPipeline(
            distilled_checkpoint_path=distilled_checkpoint_path,
            gemma_root=gemma_root,
            spatial_upsampler_path=spatial_upsampler_path,
            loras=[],
            registry=registry,
            quantization=quantization_policy,
            compilation_config=compilation_config,
            offload_mode=OffloadMode(offload_mode),
            alloc_trim_strategy=AllocatorTrimStrategy.DEFER,
        )
        tracker = TransformerWeightTracker(group=self.groups.transformer_group, no_lora_swap=no_lora_swap)

        model_config = pipeline.stage._transformer_builder.model_config().get("transformer", {})
        attention_manager = AttentionManager(
            max_tokens=sp_max_tokens,
            num_heads=model_config["num_attention_heads"],
            head_dim=model_config["attention_head_dim"],
            tensor_dtype=pipeline.dtype,
            group=self.groups.transformer_group,
        )
        pipeline.stage._transformer_builder = SequenceParallelBuilder(
            inner=pipeline.stage._transformer_builder,
            attn_mgr=attention_manager,
            registry=registry,
            tracker=tracker,
        )

        pipeline.prompt_encoder._text_encoder_builder = AccelerateGemmaBuilder(
            gemma_root_path=gemma_root,
            gemma_group=self.groups.gemma_group,
            broadcast_group=self.groups.transformer_group,
            registry=registry,
            src_rank=DRIVER_RANK,
            dtype=pipeline.dtype,
        )

        if distributed_vae:
            vae_height_tiles, vae_width_tiles = balanced_tile_split(dist.get_world_size(self.groups.vae_group))
            vae_tiling = TileCountConfig(
                height=DimensionTilingConfig(num_tiles=vae_height_tiles, overlap=vae_overlap),
                width=DimensionTilingConfig(num_tiles=vae_width_tiles, overlap=vae_overlap),
            )
            pipeline.video_decoder._decoder_builder = DistributedDecoderBuilder(
                inner=pipeline.video_decoder._decoder_builder,
                queue=vae_queue,
                vae_group=self.groups.vae_group,
                vae_tiling=vae_tiling,
                driver_rank=DRIVER_RANK,
                registry=registry,
            )

        original_video_decoder = pipeline.video_decoder
        original_audio_decoder = pipeline.audio_decoder

        def trim_before_decode() -> None:
            pipeline.stage = None
            pipeline.prompt_encoder = None
            pipeline.image_conditioner = None
            pipeline.upsampler = None
            tracker.stored_sd = None
            tracker.broadcast_sd = None
            if hasattr(tracker, "_staging"):
                tracker._staging = None
            registry.clear()
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            if dist.is_initialized():
                dist.barrier()

        class TrimmedVideoDecoder:
            def __call__(self, latent: Any, tiling_config: TilingConfig | None = None, generator: Any = None) -> Any:
                trim_before_decode()
                if (not distributed_vae) and dist.get_rank() != DRIVER_RANK:
                    return iter([])
                return original_video_decoder(latent, tiling_config, generator)

        class OptionalAudioDecoder:
            def __call__(self, latent: Any) -> Any:
                if no_audio:
                    return None
                return original_audio_decoder(latent)

        pipeline.video_decoder = TrimmedVideoDecoder()
        pipeline.audio_decoder = OptionalAudioDecoder()
        self._pipeline = pipeline
        self._distributed_vae = distributed_vae
        self._no_audio = no_audio

    @torch.inference_mode()
    def __call__(
        self,
        *,
        output_path: str,
        prompt: str,
        seed: int,
        height: int,
        width: int,
        num_frames: int,
        frame_rate: float,
        images: list[Any] | None = None,
        negative_prompt: str | None = None,
        num_inference_steps: int | None = None,
        video_guider_params: Any = None,
        audio_guider_params: Any = None,
        **_unused: Any,
    ) -> Iterator[str | None]:
        video, audio = self._pipeline(
            prompt=prompt,
            seed=seed,
            height=height,
            width=width,
            num_frames=num_frames,
            frame_rate=frame_rate,
            images=images or [],
            tiling_config=None,
        )
        torch.cuda.synchronize()
        if dist.is_initialized():
            dist.barrier()

        if dist.get_rank() != DRIVER_RANK:
            if self._distributed_vae:
                for _ in video:
                    pass
            yield None
            return

        encode_video_simple(video=video, fps=frame_rate, audio=None if self._no_audio else audio, output_path=output_path)
        yield output_path


def encode_video_simple(*, video: Any, fps: float, audio: Any, output_path: str) -> None:
    if isinstance(video, torch.Tensor):
        iterator = iter([video])
    else:
        iterator = iter(video)

    first = next(iterator, None)
    if first is None:
        raise ValueError("video is empty")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    container = av.open(output_path, mode="w")
    success = False
    try:
        stream = container.add_stream("libx264", rate=int(fps), options={"crf": "19", "preset": "veryfast"})
        stream.width = int(first.shape[2])
        stream.height = int(first.shape[1])
        stream.pix_fmt = "yuv420p"
        stream.codec_context.thread_count = 0

        for chunk in _video_chunks(first, iterator):
            frame_batch = (chunk.detach().float().clamp(0, 1) * 255).to(torch.uint8).cpu().numpy()
            for frame_array in frame_batch:
                frame = av.VideoFrame.from_ndarray(frame_array, format="rgb24")
                for packet in stream.encode(frame):
                    container.mux(packet)

        for packet in stream.encode():
            container.mux(packet)
        success = True
    finally:
        container.close()
        if not success:
            Path(output_path).unlink(missing_ok=True)


def _video_chunks(first: torch.Tensor, iterator: Iterator[Any]) -> Iterator[Any]:
    yield first
    yield from iterator
