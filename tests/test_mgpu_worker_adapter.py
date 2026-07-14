from datetime import timedelta
from io import BytesIO
import sys
import types

from gpu_server.worker_adapter.mgpu import dimensions_for_aspect_ratio
from gpu_server.worker_adapter.mgpu import frame_count_for_duration
from gpu_server.worker_adapter.mgpu import LtxMgpuExecutor
from gpu_server.worker_adapter.mgpu import _env_timedelta_seconds


def test_frame_count_for_duration_returns_8k_plus_one() -> None:
    assert frame_count_for_duration(10, 24) == 241
    assert frame_count_for_duration(1, 24) == 25
    assert frame_count_for_duration(0, 24) == 9


def test_mgpu_dimensions_are_two_stage_compatible() -> None:
    expected_dimensions = {
        "16:9": (1024, 576),
        "9:16": (576, 1024),
        "1:1": (768, 768),
        "4:3": (1024, 768),
        "3:4": (768, 1024),
        "unknown": (1024, 576),
    }

    for aspect_ratio, expected in expected_dimensions.items():
        width, height = dimensions_for_aspect_ratio(aspect_ratio)
        assert (width, height) == expected
        assert width % 64 == 0
        assert height % 64 == 0


def test_mgpu_timeout_env_returns_timedelta(monkeypatch) -> None:
    monkeypatch.setenv("MGPU_START_TIMEOUT_SECONDS", "42")

    assert _env_timedelta_seconds("MGPU_START_TIMEOUT_SECONDS", 3600) == timedelta(seconds=42)


def test_mgpu_executor_shutdowns_controller_after_task(tmp_path, monkeypatch) -> None:
    class FakeStream:
        drained = False

        def __iter__(self):
            return iter([None])

        def drain(self) -> None:
            self.drained = True

    class FakeRunner:
        def stream(self, **kwargs):
            output_path = kwargs["output_path"]
            with open(output_path, "wb") as output:
                output.write(b"video")
            return FakeStream()

    class FakeController:
        shutdown_called = False

        def shutdown(self, graceful_timeout: float) -> None:
            self.shutdown_called = True

    fake_controller = FakeController()
    executor = LtxMgpuExecutor(storage=object())

    def ensure_controller():
        executor._controller = fake_controller
        return FakeRunner()

    monkeypatch.setenv("MGPU_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(executor, "_ensure_controller", ensure_controller)
    monkeypatch.setattr(executor, "_default_video_guider_params", lambda: {})
    monkeypatch.setattr(executor, "_default_audio_guider_params", lambda: {})

    result = executor.execute({"request_params": {"prompt": "hello", "duration_seconds": 1}}, "att_test")

    assert result == b"video"
    assert fake_controller.shutdown_called is True
    assert executor._controller is None
    assert executor._vae_queue is None


def test_mgpu_executor_preprocesses_grayscale_input_with_workflow_contract(tmp_path, monkeypatch) -> None:
    from PIL import Image

    captured: dict = {}

    class ImageConditioningInput:
        def __init__(self, path: str, frame_index: int, strength: float) -> None:
            self.path = path
            self.frame_index = frame_index
            self.strength = strength

    ltx_pipelines = types.ModuleType("ltx_pipelines")
    utils = types.ModuleType("ltx_pipelines.utils")
    args = types.ModuleType("ltx_pipelines.utils.args")
    args.ImageConditioningInput = ImageConditioningInput
    monkeypatch.setitem(sys.modules, "ltx_pipelines", ltx_pipelines)
    monkeypatch.setitem(sys.modules, "ltx_pipelines.utils", utils)
    monkeypatch.setitem(sys.modules, "ltx_pipelines.utils.args", args)

    class FakeStream:
        def __iter__(self):
            return iter([None])

        def drain(self) -> None:
            return None

    class FakeRunner:
        def stream(self, **kwargs):
            captured.update(kwargs)
            with open(kwargs["output_path"], "wb") as output:
                output.write(b"video")
            return FakeStream()

    class FakeController:
        def shutdown(self, graceful_timeout: float) -> None:
            return None

    class FakeStorage:
        def read_bytes(self, storage_uri: str) -> bytes:
            assert storage_uri == "local://input"
            image = Image.new("L", (8, 6), color=128)
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            return buffer.getvalue()

    executor = LtxMgpuExecutor(storage=FakeStorage())

    def ensure_controller():
        executor._controller = FakeController()
        return FakeRunner()

    monkeypatch.setenv("MGPU_OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("MGPU_INPUT_DIR", str(tmp_path / "inputs"))
    monkeypatch.setattr(executor, "_ensure_controller", ensure_controller)
    monkeypatch.setattr(executor, "_default_video_guider_params", lambda: {})
    monkeypatch.setattr(executor, "_default_audio_guider_params", lambda: {})

    result = executor.execute(
        {
            "request_params": {"prompt": "hello", "duration_seconds": 1},
            "workflow_input_contract": {"image": {"color_mode": "RGB", "output_format": "png"}},
            "input_asset": {"storage_uri": "local://input", "content_type": "image/png"},
        },
        "att_test",
    )

    assert result == b"video"
    image_input = captured["images"][0]
    assert image_input.path.endswith("att_test_input.png")
    converted = Image.open(image_input.path)
    assert converted.mode == "RGB"
