from __future__ import annotations

import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any


class ImagePreprocessError(ValueError):
    pass


@dataclass(frozen=True)
class WorkflowImageContract:
    color_mode: str = "RGB"
    output_format: str = "png"
    alpha_background: str = "white"


def default_workflow_input_contract() -> dict[str, Any]:
    return {
        "image": {
            "color_mode": "RGB",
            "output_format": "png",
            "alpha_background": "white",
        }
    }


def image_contract_from_payload(payload: dict[str, Any]) -> WorkflowImageContract:
    contract = payload.get("workflow_input_contract") or default_workflow_input_contract()
    image_contract = contract.get("image") if isinstance(contract, dict) else None
    if not isinstance(image_contract, dict):
        image_contract = default_workflow_input_contract()["image"]
    return WorkflowImageContract(
        color_mode=str(image_contract.get("color_mode") or "RGB").upper(),
        output_format=str(image_contract.get("output_format") or "png").lower().lstrip("."),
        alpha_background=str(image_contract.get("alpha_background") or "white").lower(),
    )


def prepare_workflow_image_input(
    *,
    image_bytes: bytes,
    output_dir: Path,
    filename_stem: str,
    contract: WorkflowImageContract,
) -> Path:
    try:
        from PIL import Image, UnidentifiedImageError
    except Exception as exc:  # pragma: no cover - worker images install Pillow through ComfyUI/LTX.
        raise ImagePreprocessError("Pillow is required for workflow image preprocessing") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = _suffix_for_format(contract.output_format)
    output_path = output_dir / f"{filename_stem}{suffix}"
    temp_name: str | None = None
    try:
        try:
            image = Image.open(BytesIO(image_bytes))
            image.load()
        except UnidentifiedImageError as exc:
            raise ImagePreprocessError("Input image could not be decoded") from exc

        image = _apply_color_mode(image, contract)
        save_format = _pillow_format(contract.output_format)
        with tempfile.NamedTemporaryFile(dir=output_dir, suffix=suffix, delete=False) as temp_file:
            temp_name = temp_file.name
        image.save(temp_name, format=save_format)
        Path(temp_name).replace(output_path)
        temp_name = None
        return output_path
    except ImagePreprocessError:
        raise
    except Exception as exc:
        raise ImagePreprocessError(f"Input image preprocessing failed: {exc}") from exc
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)


def _apply_color_mode(image: Any, contract: WorkflowImageContract) -> Any:
    if contract.color_mode == "RGB":
        if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
            from PIL import Image

            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, _background_color(contract.alpha_background))
            background.paste(rgba, mask=rgba.getchannel("A"))
            return background
        return image.convert("RGB")
    return image.convert(contract.color_mode)


def _background_color(value: str) -> tuple[int, int, int]:
    if value == "black":
        return (0, 0, 0)
    return (255, 255, 255)


def _suffix_for_format(output_format: str) -> str:
    if output_format in {"jpg", "jpeg"}:
        return ".jpg"
    return f".{output_format or 'png'}"


def _pillow_format(output_format: str) -> str:
    if output_format in {"jpg", "jpeg"}:
        return "JPEG"
    return output_format.upper() or "PNG"
