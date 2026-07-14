from __future__ import annotations

from io import BytesIO

from gpu_server.worker_adapter.workflow_inputs import WorkflowImageContract
from gpu_server.worker_adapter.workflow_inputs import ImagePreprocessError
from gpu_server.worker_adapter.workflow_inputs import prepare_workflow_image_input
from gpu_server.worker_adapter.runtime import _error_code


def test_prepare_workflow_image_input_converts_grayscale_to_rgb_png(tmp_path) -> None:
    from PIL import Image

    source = Image.new("L", (8, 6), color=128)
    buffer = BytesIO()
    source.save(buffer, format="PNG")

    output_path = prepare_workflow_image_input(
        image_bytes=buffer.getvalue(),
        output_dir=tmp_path,
        filename_stem="input",
        contract=WorkflowImageContract(color_mode="RGB", output_format="png"),
    )

    assert output_path.name == "input.png"
    converted = Image.open(output_path)
    assert converted.mode == "RGB"
    assert converted.size == (8, 6)


def test_image_preprocess_error_has_specific_error_code() -> None:
    assert _error_code(ImagePreprocessError("bad image")) == "IMAGE_PREPROCESS_FAILED"
