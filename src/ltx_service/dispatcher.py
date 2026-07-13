from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any


def dispatch_once(control_plane_url: str, admin_token: str, timeout_seconds: int = 10) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{control_plane_url.rstrip('/')}/internal/dispatch/run-once",
        headers={"X-Admin-Token": admin_token},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def main() -> None:
    control_plane_url = os.getenv("CONTROL_PLANE_URL", "http://control-plane:8000")
    admin_token = os.getenv("LTX_ADMIN_TOKEN") or os.getenv("ADMIN_TOKEN")
    if not admin_token:
        raise RuntimeError("LTX_ADMIN_TOKEN or ADMIN_TOKEN is required")

    interval_seconds = env_int("DISPATCH_INTERVAL_SECONDS", 5)
    timeout_seconds = env_int("DISPATCH_TIMEOUT_SECONDS", 10)
    while True:
        try:
            outcome = dispatch_once(control_plane_url, admin_token, timeout_seconds)
            print(f"dispatch outcome={json.dumps(outcome, sort_keys=True)}", flush=True)
        except urllib.error.HTTPError as exc:
            print(f"dispatch http_error status={exc.code}", flush=True)
        except Exception as exc:
            print(f"dispatch error={exc.__class__.__name__}: {exc}", flush=True)
        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
