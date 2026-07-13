from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class ComfyUIClient:
    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_json(self, path: str) -> dict[str, Any]:
        with urllib.request.urlopen(f"{self.base_url}{path}", timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_bytes(self, path: str, params: dict[str, str]) -> bytes:
        query = urllib.parse.urlencode(params)
        with urllib.request.urlopen(f"{self.base_url}{path}?{query}", timeout=self.timeout) as response:
            return response.read()


def load_workflow_api(path: Path, client: ComfyUIClient) -> dict[str, Any]:
    workflow = json.loads(path.read_text())
    if "nodes" not in workflow:
        return workflow
    object_info = client.get_json("/object_info")
    return convert_ui_workflow_to_api(workflow, object_info)


def convert_ui_workflow_to_api(workflow: dict[str, Any], object_info: dict[str, Any]) -> dict[str, Any]:
    nodes = {str(node["id"]): node for node in workflow.get("nodes", []) if int(node.get("mode", 0)) == 0}
    link_sources = {
        int(link[0]): (str(link[1]), int(link[2]))
        for link in workflow.get("links", [])
        if str(link[1]) in nodes and str(link[3]) in nodes
    }
    api: dict[str, Any] = {}
    for node_id, node in nodes.items():
        class_type = node["type"]
        inputs: dict[str, Any] = {}
        connected = set()
        for input_item in node.get("inputs", []):
            link_id = input_item.get("link")
            if link_id is None or int(link_id) not in link_sources:
                continue
            source_id, source_slot = link_sources[int(link_id)]
            inputs[input_item["name"]] = [source_id, source_slot]
            connected.add(input_item["name"])

        widget_values = list(node.get("widgets_values") or [])
        for input_name, value in zip(_widget_input_names(class_type, object_info), widget_values):
            if input_name not in connected and input_name not in inputs:
                inputs[input_name] = value

        api[node_id] = {
            "class_type": class_type,
            "inputs": inputs,
            "_meta": {"title": node.get("title") or node.get("properties", {}).get("Node name for S&R") or class_type},
        }
    return api


def inject_assignment_parameters(
    prompt: dict[str, Any],
    assignment: dict[str, Any],
    input_image_name: str | None,
    output_prefix: str,
) -> dict[str, Any]:
    request_params = assignment.get("request_params") or {}
    positive = str(request_params.get("prompt") or "")
    negative = str(request_params.get("negative_prompt") or "")
    fps = int(request_params.get("frame_rate") or 24)
    duration = int(request_params.get("duration_seconds") or 5)
    frame_count = max(9, duration * fps + 1)
    width, height = dimensions_for_aspect_ratio(str(request_params.get("aspect_ratio") or "16:9"))
    seed = request_params.get("seed")

    patched = json.loads(json.dumps(prompt))
    for node in patched.values():
        class_type = node.get("class_type")
        inputs = node.setdefault("inputs", {})
        title = str(node.get("_meta", {}).get("title") or "").lower()
        if class_type == "CLIPTextEncode" and "text" in inputs:
            if "negative" in title:
                inputs["text"] = negative
            elif "positive" in title or positive:
                inputs["text"] = positive
        if class_type == "LoadImage" and input_image_name:
            inputs["image"] = input_image_name
        if class_type in {"EmptyLTXVLatentVideo", "LTXVImgToVideo", "LTXVImgToVideoAdvanced", "LTXVBaseSampler"}:
            if "width" in inputs:
                inputs["width"] = width
            if "height" in inputs:
                inputs["height"] = height
            if "length" in inputs:
                inputs["length"] = frame_count
            if "num_frames" in inputs:
                inputs["num_frames"] = frame_count
        if class_type == "LTXVConditioning" and "frame_rate" in inputs:
            inputs["frame_rate"] = fps
        if class_type == "SaveVideo":
            inputs["filename_prefix"] = output_prefix
        if seed is not None:
            for key in ("seed", "noise_seed"):
                if key in inputs:
                    inputs[key] = int(seed)
    return patched


def run_prompt_and_fetch_video(
    client: ComfyUIClient,
    prompt: dict[str, Any],
    poll_interval_seconds: int,
    timeout_seconds: int,
) -> bytes:
    submitted = client.post_json("/prompt", {"prompt": prompt})
    prompt_id = submitted["prompt_id"]
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        history = client.get_json(f"/history/{prompt_id}")
        item = history.get(prompt_id)
        if item:
            status = item.get("status", {})
            if status.get("completed"):
                return _fetch_first_video(client, item.get("outputs", {}))
            messages = " ".join(str(message) for message in status.get("messages", []))
            if "error" in messages.lower():
                raise RuntimeError(messages)
        time.sleep(poll_interval_seconds)
    raise TimeoutError(f"ComfyUI prompt timed out: {prompt_id}")


def dimensions_for_aspect_ratio(aspect_ratio: str) -> tuple[int, int]:
    presets = {
        "16:9": (960, 544),
        "9:16": (544, 960),
        "1:1": (768, 768),
        "4:3": (896, 672),
        "3:4": (672, 896),
    }
    return presets.get(aspect_ratio, presets["16:9"])


def _widget_input_names(class_type: str, object_info: dict[str, Any]) -> list[str]:
    node_info = object_info.get(class_type, {})
    inputs = node_info.get("input", {})
    names: list[str] = []
    for section in ("required", "optional"):
        for name, spec in inputs.get(section, {}).items():
            if _is_widget_spec(spec):
                names.append(name)
    return names


def _is_widget_spec(spec: Any) -> bool:
    if not isinstance(spec, list) or not spec:
        return False
    first = spec[0]
    return isinstance(first, list) or first in {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}


def _fetch_first_video(client: ComfyUIClient, outputs: dict[str, Any]) -> bytes:
    for output in outputs.values():
        for key in ("videos", "gifs", "images"):
            for item in output.get(key, []) if isinstance(output, dict) else []:
                filename = item.get("filename")
                if not filename:
                    continue
                return client.get_bytes(
                    "/view",
                    {
                        "filename": filename,
                        "subfolder": item.get("subfolder") or "",
                        "type": item.get("type") or "output",
                    },
                )
    raise RuntimeError("ComfyUI completed without a video output")
