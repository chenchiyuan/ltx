from __future__ import annotations

from gpu_server.worker_adapter.comfyui import convert_ui_workflow_to_api


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
