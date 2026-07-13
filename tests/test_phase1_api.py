from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

API_KEY = "test-api-key"
ADMIN_TOKEN = "test-admin-token"
AUTH = {"Authorization": f"Bearer {API_KEY}"}
ADMIN = {"X-Admin-Token": ADMIN_TOKEN}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'ltx.db'}"
    storage_root = tmp_path / "objects"
    monkeypatch.setenv("LTX_DATABASE_URL", database_url)
    monkeypatch.setenv("LTX_STORAGE_ROOT", str(storage_root))
    monkeypatch.setenv("LTX_BOOTSTRAP_API_KEY", API_KEY)
    monkeypatch.setenv("LTX_ADMIN_TOKEN", ADMIN_TOKEN)

    from ltx_service.app import create_app
    from ltx_service.config import Settings

    settings = Settings(
        database_url=database_url,
        storage_root=storage_root,
        bootstrap_api_key=API_KEY,
        admin_token=ADMIN_TOKEN,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_auth_health_and_quota_guards(client):
    response = client.post("/v1/video-generations", json=_text_payload(), headers={"Authorization": "Bearer bad"})
    _assert_error(response, 401, "AUTH_INVALID_API_KEY")

    _add_api_key(client, "disabled-key", status="disabled")
    response = client.post(
        "/v1/video-generations",
        json=_text_payload(),
        headers={"Authorization": "Bearer disabled-key"},
    )
    _assert_error(response, 403, "AUTH_KEY_DISABLED")

    _add_api_key(client, "quota-key", quota_task_limit=0)
    response = client.post(
        "/v1/video-generations",
        json=_text_payload(),
        headers={"Authorization": "Bearer quota-key"},
    )
    _assert_error(response, 429, "QUOTA_EXCEEDED")

    health = client.get("/health").json()
    assert health["status"] == "ok"
    assert health["database"] == "ok"
    assert health["storage"] == "ok"
    assert health["web"] == "ok"
    assert health["executor"]["executor_type"] == "mock-local"
    assert API_KEY not in str(health)
    assert ADMIN_TOKEN not in str(health)


def test_sqlite_database_parent_directory_is_created(tmp_path):
    from ltx_service.config import Settings
    from ltx_service.database import create_session_factory

    database_path = tmp_path / "nested" / "state" / "ltx.db"
    settings = Settings(database_url=f"sqlite:///{database_path}", storage_root=tmp_path / "objects")

    create_session_factory(settings)

    assert database_path.exists()


def test_asset_upload_roundtrip_and_ownership(client):
    response = client.post(
        "/v1/assets/uploads",
        json={"filename": "input.txt", "content_type": "text/plain", "size_bytes": 4},
        headers=AUTH,
    )
    _assert_error(response, 422, "REQUEST_INVALID_PARAMETER")

    asset_id = _upload_image(client)
    response = client.get(f"/v1/assets/{asset_id}/content", headers=AUTH)
    assert response.status_code == 200
    assert response.content == b"fake image"
    assert response.headers["content-type"] == "image/png"

    _add_api_key(client, "other-key")
    response = client.get(
        f"/v1/assets/{asset_id}/content",
        headers={"Authorization": "Bearer other-key"},
    )
    _assert_error(response, 404, "ASSET_NOT_FOUND")


def test_text_to_video_success_result_usage_and_metrics(client):
    headers = {**AUTH, "Idempotency-Key": "same-request"}
    first = client.post("/v1/video-generations", json=_text_payload(prompt="hello"), headers=headers)
    assert first.status_code == 200
    task_id = first.json()["task_id"]
    assert first.json()["status"] == "queued"
    assert first.json()["estimated_gpu_seconds"] == 180

    second = client.post("/v1/video-generations", json=_text_payload(prompt="hello"), headers=headers)
    assert second.status_code == 200
    assert second.json()["task_id"] == task_id

    dispatched = client.post("/internal/dispatch/run-once", headers=ADMIN)
    assert dispatched.status_code == 200
    assert dispatched.json()["dispatched"] is True

    running = client.get(f"/v1/video-generations/{task_id}", headers=AUTH)
    assert running.status_code == 200
    assert running.json()["status"] == "running"
    assert running.json()["attempt_count"] == 1

    completed = client.post("/internal/dispatch/complete-running", headers=ADMIN)
    assert completed.status_code == 200
    assert completed.json()["status"] == "succeeded"
    assert completed.json()["attempt_count"] == 1

    result = client.get(f"/v1/video-generations/{task_id}/result", headers=AUTH)
    assert result.status_code == 200
    outputs = result.json()["outputs"]
    assert len(outputs) == 1
    video = client.get(outputs[0]["download_url"], headers=AUTH)
    assert video.status_code == 200
    assert b"mock video" in video.content

    usage = client.get("/admin/usage", headers=ADMIN)
    assert usage.status_code == 200
    assert usage.json()[0]["task_count"] == 1
    assert usage.json()[0]["succeeded_count"] == 1
    assert usage.json()[0]["attempt_count"] == 1
    assert usage.json()[0]["estimated_gpu_seconds"] == 180

    metrics = client.get("/metrics").text
    assert 'ltx_tasks_total{status="succeeded"} 1' in metrics
    assert "ltx_task_success_rate 1.000" in metrics
    assert 'ltx_task_attempts_total{attempt_count="1"} 1' in metrics


def test_image_to_video_requires_uploaded_asset_and_succeeds(client):
    response = client.post("/v1/video-generations", json=_image_payload(), headers=AUTH)
    _assert_error(response, 422, "REQUEST_IMAGE_REQUIRED")

    asset_id = _upload_image(client)
    created = client.post(
        "/v1/video-generations",
        json=_image_payload(image_asset_id=asset_id),
        headers=AUTH,
    )
    assert created.status_code == 200
    assert created.json()["status"] == "queued"
    task_id = created.json()["task_id"]

    _run_one_attempt(client)
    result = client.get(f"/v1/video-generations/{task_id}/result", headers=AUTH)
    assert result.status_code == 200
    assert result.json()["status"] == "succeeded"


def test_cancel_queued_task_and_reject_terminal_cancel(client):
    created = client.post("/v1/video-generations", json=_text_payload(prompt="cancel me"), headers=AUTH)
    assert created.status_code == 200
    task_id = created.json()["task_id"]

    canceled = client.post(f"/v1/video-generations/{task_id}/cancel", headers=AUTH)
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceled"
    assert canceled.json()["progress"]["stage"] == "canceled"

    status = client.get(f"/v1/video-generations/{task_id}", headers=AUTH)
    assert status.status_code == 200
    assert status.json()["status"] == "canceled"

    result = client.get(f"/v1/video-generations/{task_id}/result", headers=AUTH)
    _assert_error(result, 409, "TASK_RESULT_NOT_READY")

    canceled_again = client.post(f"/v1/video-generations/{task_id}/cancel", headers=AUTH)
    _assert_error(canceled_again, 409, "TASK_NOT_CANCELABLE")


def test_retryable_failure_requeues_then_succeeds(client):
    created = client.post(
        "/v1/video-generations",
        json=_text_payload(prompt="TRANSIENT_ONCE then recover"),
        headers=AUTH,
    )
    task_id = created.json()["task_id"]

    first_attempt = _run_one_attempt(client)
    assert first_attempt["status"] == "queued"
    assert first_attempt["attempt_count"] == 1

    queued = client.get(f"/v1/video-generations/{task_id}", headers=AUTH).json()
    assert queued["status"] == "queued"
    assert queued["error"] == "COMFYUI_PROMPT_FAILED"

    filtered = client.get(
        "/admin/tasks",
        params={"status": "queued", "mode": "text_to_video", "profile": "fast", "error_code": "COMFYUI_PROMPT_FAILED"},
        headers=ADMIN,
    )
    assert filtered.status_code == 200
    assert [item["task_id"] for item in filtered.json()] == [task_id]

    second_attempt = _run_one_attempt(client)
    assert second_attempt["status"] == "succeeded"
    assert second_attempt["attempt_count"] == 2

    usage = client.get("/admin/usage", headers=ADMIN).json()
    assert usage[0]["task_count"] == 1
    assert usage[0]["attempt_count"] == 2

    metrics = client.get("/metrics").text
    assert 'ltx_attempt_failures_total{error_class="transient"} 1' in metrics


def test_invalid_input_fails_without_automatic_retry_and_can_be_manually_retried(client):
    created = client.post(
        "/v1/video-generations",
        json=_text_payload(prompt="INVALID_INPUT"),
        headers=AUTH,
    )
    task_id = created.json()["task_id"]

    completed = _run_one_attempt(client)
    assert completed["status"] == "failed"
    assert completed["attempt_count"] == 1

    no_dispatch = client.post("/internal/dispatch/run-once", headers=ADMIN)
    assert no_dispatch.status_code == 200
    assert no_dispatch.json()["dispatched"] is False

    failed = client.get(f"/v1/video-generations/{task_id}", headers=AUTH).json()
    assert failed["status"] == "failed"
    assert failed["error"] == "REQUEST_INVALID_PARAMETER"

    retried = client.post(f"/admin/tasks/{task_id}/retry", headers=ADMIN)
    assert retried.status_code == 200
    assert retried.json()["status"] == "queued"

    completed_again = _run_one_attempt(client)
    assert completed_again["status"] == "failed"
    assert completed_again["attempt_count"] == 2


def test_admin_workflow_lifecycle_and_access_control(client):
    response = client.get("/admin/tasks")
    _assert_error(response, 401, "ADMIN_TOKEN_REQUIRED")

    workflows = client.get("/admin/workflow-templates", headers=ADMIN)
    assert workflows.status_code == 200
    payload = workflows.json()
    assert {item["mode"] for item in payload["templates"]} == {"text_to_video", "image_to_video"}
    assert {item["profile"] for item in payload["profiles"]} == {"fast", "quality"}

    text_template_id = next(item["id"] for item in payload["templates"] if item["mode"] == "text_to_video")
    original_version_id = next(
        item["id"]
        for item in payload["versions"]
        if item["template_id"] == text_template_id and item["status"] == "published"
    )

    created = client.post(
        "/admin/workflow-versions",
        json={
            "template_id": text_template_id,
            "source_workflow_json": {"name": "candidate-source"},
            "api_workflow_json": {"name": "candidate-api"},
        },
        headers=ADMIN,
    )
    assert created.status_code == 200
    candidate_id = created.json()["id"]
    assert created.json()["status"] == "draft"

    tested = client.post(f"/admin/workflow-versions/{candidate_id}/test", headers=ADMIN)
    assert tested.status_code == 200
    assert tested.json()["status"] == "testing"

    published = client.post(f"/admin/workflow-versions/{candidate_id}/publish", headers=ADMIN)
    assert published.status_code == 200
    assert published.json()["status"] == "published"

    task = client.post("/v1/video-generations", json=_text_payload(prompt="uses new version"), headers=AUTH)
    assert task.status_code == 200

    rolled_back = client.post(f"/admin/workflow-versions/{original_version_id}/rollback", headers=ADMIN)
    assert rolled_back.status_code == 200
    assert rolled_back.json()["status"] == "published"

    workers = client.get("/admin/workers", headers=ADMIN)
    assert workers.status_code == 200
    assert workers.json()["executor"]["executor_type"] == "mock-local"
    assert workers.json()["workers"] == []


def _upload_image(client: TestClient) -> str:
    created = client.post(
        "/v1/assets/uploads",
        json={"filename": "input.png", "content_type": "image/png", "size_bytes": 10},
        headers=AUTH,
    )
    assert created.status_code == 200
    asset_id = created.json()["asset_id"]
    uploaded = client.put(created.json()["upload_url"], content=b"fake image", headers=AUTH)
    assert uploaded.status_code == 200
    assert uploaded.json()["status"] == "uploaded"
    return asset_id


def _run_one_attempt(client: TestClient) -> dict:
    dispatched = client.post("/internal/dispatch/run-once", headers=ADMIN)
    assert dispatched.status_code == 200
    assert dispatched.json()["dispatched"] is True
    completed = client.post("/internal/dispatch/complete-running", headers=ADMIN)
    assert completed.status_code == 200
    assert completed.json()["completed"] is True
    return completed.json()


def _text_payload(prompt: str = "hello") -> dict:
    return {
        "mode": "text_to_video",
        "prompt": prompt,
        "profile": "fast",
        "duration_seconds": 5,
        "aspect_ratio": "16:9",
    }


def _image_payload(image_asset_id: str | None = None) -> dict:
    payload = {
        "mode": "image_to_video",
        "prompt": "animate input",
        "profile": "fast",
        "duration_seconds": 5,
        "aspect_ratio": "16:9",
    }
    if image_asset_id:
        payload["image_asset_id"] = image_asset_id
    return payload


def _add_api_key(client: TestClient, raw_key: str, status: str = "active", quota_task_limit: int | None = None) -> None:
    from ltx_service.ids import new_id
    from ltx_service.models import ApiKey
    from ltx_service.security import hash_api_key

    with client.app.state.ltx.session_factory() as session:
        session.add(
            ApiKey(
                id=new_id("key"),
                key_hash=hash_api_key(raw_key),
                name=raw_key,
                status=status,
                quota_task_limit=quota_task_limit,
            )
        )
        session.commit()


def _assert_error(response, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    assert response.json()["detail"]["error"]["code"] == code
