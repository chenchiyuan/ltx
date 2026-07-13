from __future__ import annotations

import urllib.error

from gpu_server.worker_adapter.comfyui import convert_ui_workflow_to_api
from gpu_server.worker_adapter.comfyui import run_prompt_and_fetch_video


def test_ui_workflow_conversion_does_not_consume_socket_inputs_as_widgets() -> None:
    workflow = {
        "nodes": [
            {"id": 1, "type": "CheckpointLoaderSimple", "inputs": [], "widgets_values": ["model.safetensors"]},
            {
                "id": 2,
                "type": "LoraLoaderModelOnly",
                "inputs": [{"name": "model", "link": 10}],
                "widgets_values": ["ltxv/ltx2/ltx-2.3-22b-distilled-lora-384-1.1.safetensors", 0.5],
            },
            {
                "id": 3,
                "type": "SaveVideo",
                "inputs": [{"name": "video", "link": 11}],
                "widgets_values": ["output", "mp4", "h264"],
            },
            {"id": 4, "type": "VideoSource", "inputs": [], "widgets_values": []},
        ],
        "links": [
            [10, 1, 0, 2, 0, "model"],
            [11, 4, 0, 3, 0, "video"],
        ],
    }
    object_info = {
        "CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["model.safetensors"]]}}},
        "VideoSource": {"input": {}},
        "LoraLoaderModelOnly": {
            "input": {
                "required": {
                    "model": ["MODEL"],
                    "lora_name": [["ltxv/ltx2/ltx-2.3-22b-distilled-lora-384-1.1.safetensors"]],
                    "strength_model": ["FLOAT", {"default": 1.0}],
                }
            }
        },
        "SaveVideo": {
            "input": {
                "required": {
                    "video": ["VIDEO"],
                    "filename_prefix": ["STRING", {"default": "video/ComfyUI"}],
                    "format": ["COMBO", {"default": "auto"}],
                    "codec": ["COMBO", {"default": "auto"}],
                }
            }
        },
    }

    converted = convert_ui_workflow_to_api(workflow, object_info)

    assert converted["2"]["inputs"] == {
        "model": ["1", 0],
        "lora_name": "ltxv/ltx2/ltx-2.3-22b-distilled-lora-384-1.1.safetensors",
        "strength_model": 0.5,
    }
    assert converted["3"]["inputs"] == {
        "video": ["4", 0],
        "filename_prefix": "output",
        "format": "mp4",
        "codec": "h264",
    }


def test_ui_workflow_conversion_expands_dynamic_combo_widget_inputs() -> None:
    workflow = {
        "nodes": [
            {"id": 1, "type": "ImageSource", "inputs": [], "widgets_values": []},
            {
                "id": 2,
                "type": "ResizeImageMaskNode",
                "inputs": [{"name": "input", "type": "IMAGE,MASK", "link": 10}],
                "widgets_values": ["scale longer dimension", 1536, "lanczos"],
            },
        ],
        "links": [[10, 1, 0, 2, 0, "input"]],
    }
    object_info = {
        "ImageSource": {"input": {}},
        "ResizeImageMaskNode": {
            "input": {
                "required": {
                    "input": ["COMFY_MATCHTYPE_V3", {"rawLink": True}],
                    "resize_type": [
                        "COMFY_DYNAMICCOMBO_V3",
                        {
                            "options": [
                                {
                                    "key": "scale longer dimension",
                                    "inputs": {
                                        "required": {
                                            "match": ["IMAGE,MASK"],
                                            "longer_size": ["INT", {"default": 1024}],
                                        }
                                    },
                                },
                            ]
                        },
                    ],
                    "scale_method": [
                        "COMBO",
                        {"default": "lanczos", "options": ["nearest-exact", "bilinear", "area", "bicubic", "lanczos"]},
                    ],
                }
            }
        },
    }

    converted = convert_ui_workflow_to_api(workflow, object_info)

    assert converted["2"]["inputs"] == {
        "input": ["1", 0],
        "resize_type": "scale longer dimension",
        "resize_type.longer_size": 1536,
        "scale_method": "lanczos",
    }


def test_run_prompt_tolerates_history_404_until_output_is_ready() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.history_calls = 0

        def post_json(self, path: str, payload: dict) -> dict:
            assert path == "/prompt"
            assert "prompt" in payload
            return {"prompt_id": "prompt-1"}

        def get_json(self, path: str) -> dict:
            assert path == "/history/prompt-1"
            self.history_calls += 1
            if self.history_calls == 1:
                raise urllib.error.HTTPError(path, 404, "Not Found", hdrs=None, fp=None)
            return {
                "prompt-1": {
                    "status": {"completed": True},
                    "outputs": {"1": {"videos": [{"filename": "out.mp4", "type": "output"}]}},
                }
            }

        def get_bytes(self, path: str, params: dict[str, str]) -> bytes:
            assert path == "/view"
            assert params["filename"] == "out.mp4"
            return b"video"

    assert run_prompt_and_fetch_video(FakeClient(), {"1": {}}, 0, 5) == b"video"
