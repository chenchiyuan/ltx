from __future__ import annotations

from fastapi.testclient import TestClient
import json
import pytest

API_KEY = "test-api-key"
ADMIN_TOKEN = "test-admin-token"
WORKER_TOKEN = "test-worker-token"
AUTH = {"Authorization": f"Bearer {API_KEY}"}
ADMIN = {"X-Admin-Token": ADMIN_TOKEN}
WORKER = {"X-Worker-Token": WORKER_TOKEN}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'ltx.db'}"
    storage_root = tmp_path / "objects"
    monkeypatch.setenv("LTX_DATABASE_URL", database_url)
    monkeypatch.setenv("LTX_STORAGE_ROOT", str(storage_root))
    monkeypatch.setenv("LTX_BOOTSTRAP_API_KEY", API_KEY)
    monkeypatch.setenv("LTX_ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("LTX_WORKER_TOKEN", WORKER_TOKEN)

    from ltx_service.app import create_app
    from ltx_service.config import Settings

    settings = Settings(
        database_url=database_url,
        storage_root=storage_root,
        bootstrap_api_key=API_KEY,
        admin_token=ADMIN_TOKEN,
        worker_token=WORKER_TOKEN,
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


def test_database_adds_worker_id_column_to_existing_attempts_table(tmp_path):
    from sqlalchemy import create_engine, inspect, text

    from ltx_service.config import Settings
    from ltx_service.database import create_session_factory

    database_path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{database_path}", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE task_attempts (
                    id VARCHAR PRIMARY KEY,
                    task_id VARCHAR NOT NULL,
                    attempt_no INTEGER NOT NULL,
                    executor_type VARCHAR NOT NULL,
                    status VARCHAR NOT NULL
                )
                """
            )
        )

    create_session_factory(Settings(database_url=f"sqlite:///{database_path}", storage_root=tmp_path / "objects"))

    columns = {column["name"] for column in inspect(create_engine(f"sqlite:///{database_path}", future=True)).get_columns("task_attempts")}
    assert "worker_id" in columns


def test_phase2_local_shared_storage_uses_adapter_uris_without_path_leaks(tmp_path):
    from ltx_service.app import create_app
    from ltx_service.config import Settings
    from ltx_service.models import Asset

    database_url = f"sqlite:///{tmp_path / 'ltx.db'}"
    storage_root = tmp_path / "shared-storage"
    settings = Settings(
        database_url=database_url,
        storage_backend="local_shared",
        storage_root=storage_root,
        bootstrap_api_key=API_KEY,
        admin_token=ADMIN_TOKEN,
    )

    with TestClient(create_app(settings)) as test_client:
        health = test_client.get("/health").json()
        assert health["status"] == "ok"
        assert health["storage"] == "ok"
        assert health["storage_detail"]["type"] == "local_shared"
        assert str(storage_root) not in str(health)

        asset_id = _upload_image(test_client)
        with test_client.app.state.ltx.session_factory() as session:
            input_asset = session.get(Asset, asset_id)
            assert input_asset is not None
            assert input_asset.storage_uri.startswith("local://inputs/")
            assert str(storage_root) not in input_asset.storage_uri

        created = test_client.post("/v1/video-generations", json=_text_payload(prompt="uri boundary"), headers=AUTH)
        assert created.status_code == 200
        task_id = created.json()["task_id"]
        _run_one_attempt(test_client)

        result = test_client.get(f"/v1/video-generations/{task_id}/result", headers=AUTH)
        assert result.status_code == 200
        with test_client.app.state.ltx.session_factory() as session:
            output_asset = session.query(Asset).filter_by(task_id=task_id, kind="video").one()
            assert output_asset.storage_uri.startswith("local://outputs/")
            assert str(storage_root) not in output_asset.storage_uri


def test_local_shared_storage_health_fails_when_root_is_not_writable(tmp_path):
    from ltx_service.app import create_app
    from ltx_service.config import Settings
    from ltx_service.models import Asset, VideoTask

    blocked_root = tmp_path / "storage-file"
    blocked_root.write_text("not a directory")
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'ltx.db'}",
        storage_backend="local_shared",
        storage_root=blocked_root,
        bootstrap_api_key=API_KEY,
        admin_token=ADMIN_TOKEN,
    )

    with TestClient(create_app(settings), raise_server_exceptions=False) as test_client:
        health = test_client.get("/health").json()
        assert health["status"] == "degraded"
        assert health["storage"] == "failed"
        assert health["storage_detail"]["type"] == "local_shared"
        assert "FileExistsError" in health["storage_detail"]["reason"]
        assert str(blocked_root) not in str(health)

        created = test_client.post("/v1/video-generations", json=_text_payload(prompt="storage fails"), headers=AUTH)
        assert created.status_code == 200
        task_id = created.json()["task_id"]

        dispatched = test_client.post("/internal/dispatch/run-once", headers=ADMIN)
        assert dispatched.status_code == 200
        assert dispatched.json()["dispatched"] is True

        completed = test_client.post("/internal/dispatch/complete-running", headers=ADMIN)
        assert completed.status_code == 500

        with test_client.app.state.ltx.session_factory() as session:
            task = session.get(VideoTask, task_id)
            assert task is not None
            assert task.status == "running"
            outputs = session.query(Asset).filter_by(task_id=task_id, kind="video").all()
            assert outputs == []


def test_minio_backend_required_env_reports_missing_variables(monkeypatch):
    from ltx_service.config import Settings

    monkeypatch.setenv("LTX_REQUIRE_ENV", "true")
    monkeypatch.setenv("LTX_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("LTX_STORAGE_BACKEND", "minio")
    monkeypatch.setenv("LTX_BOOTSTRAP_API_KEY", API_KEY)
    monkeypatch.setenv("LTX_ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("LTX_WORKER_TOKEN", WORKER_TOKEN)

    settings = Settings.from_env()
    with pytest.raises(RuntimeError) as exc_info:
        settings.validate_required()

    message = str(exc_info.value)
    assert "LTX_MINIO_ENDPOINT" in message
    assert "LTX_MINIO_ACCESS_KEY" in message
    assert "LTX_MINIO_SECRET_KEY" in message
    assert "LTX_MINIO_BUCKET" in message


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


def test_worker_registry_registers_heartbeats_and_admin_lists_workers(client):
    first_worker_id = None
    for gpu_index in range(8):
        registered = client.post(
            "/internal/workers/register",
            json=_worker_payload(gpu_index),
            headers=WORKER,
        )
        assert registered.status_code == 200
        payload = registered.json()
        assert payload["worker_id"].startswith("wrk_")
        assert payload["status"] == "idle"
        if gpu_index == 0:
            first_worker_id = payload["worker_id"]

    duplicate = client.post("/internal/workers/register", json=_worker_payload(0), headers=WORKER)
    assert duplicate.status_code == 200
    assert duplicate.json()["worker_id"] == first_worker_id

    heartbeat = client.post(
        f"/internal/workers/{first_worker_id}/heartbeat",
        json={
            "status": "busy",
            "queue_depth": 1,
            "capabilities": {
                "modes": ["text_to_video"],
                "profiles": ["fast"],
                "ltx_profile": "distilled_single_stage",
            },
            "current_attempt_id": "att_test",
        },
        headers=WORKER,
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["status"] == "busy"
    assert heartbeat.json()["queue_depth"] == 1

    workers = client.get("/admin/workers", headers=ADMIN)
    assert workers.status_code == 200
    payload = workers.json()
    assert payload["phase"] == "phase-2-worker-registry"
    assert len(payload["workers"]) == 8
    by_gpu = {item["gpu_index"]: item for item in payload["workers"]}
    assert by_gpu[0]["worker_id"] == first_worker_id
    assert by_gpu[0]["worker_name"] == "gpu-host-01-gpu-0"
    assert by_gpu[0]["status"] == "busy"
    assert by_gpu[0]["queue_depth"] == 1
    assert by_gpu[0]["current_attempt_id"] == "att_test"
    assert by_gpu[0]["heartbeat_age_seconds"] >= 0
    assert by_gpu[7]["status"] == "idle"

    restarted = client.post("/internal/workers/register", json=_worker_payload(0), headers=WORKER)
    assert restarted.status_code == 200
    assert restarted.json()["worker_id"] == first_worker_id
    assert restarted.json()["status"] == "idle"
    assert restarted.json()["current_attempt_id"] is None

    missing_token = client.post("/internal/workers/register", json=_worker_payload(9))
    _assert_error(missing_token, 401, "WORKER_TOKEN_REQUIRED")

    wrong_token = client.post(
        "/internal/workers/register",
        json=_worker_payload(9),
        headers={"X-Worker-Token": "wrong"},
    )
    _assert_error(wrong_token, 403, "WORKER_FORBIDDEN")


def test_worker_registry_marks_stale_workers_unavailable(client):
    from datetime import timedelta

    from ltx_service.models import GpuWorker
    from ltx_service.worker_registry import HEARTBEAT_TIMEOUT_SECONDS, list_available_workers, utc_now

    registered = client.post("/internal/workers/register", json=_worker_payload(0), headers=WORKER)
    assert registered.status_code == 200
    worker_id = registered.json()["worker_id"]

    with client.app.state.ltx.session_factory() as session:
        worker = session.get(GpuWorker, worker_id)
        assert worker is not None
        worker.last_heartbeat_at = utc_now() - timedelta(seconds=HEARTBEAT_TIMEOUT_SECONDS + 1)
        worker.status = "idle"
        session.commit()

    workers = client.get("/admin/workers", headers=ADMIN)
    assert workers.status_code == 200
    assert workers.json()["workers"][0]["status"] == "offline"

    with client.app.state.ltx.session_factory() as session:
        assert list_available_workers(session) == []


def test_gpu_worker_dispatch_keeps_task_queued_when_capacity_unavailable(tmp_path):
    with _gpu_client(tmp_path) as client:
        created = client.post("/v1/video-generations", json=_text_payload(prompt="needs capacity"), headers=AUTH)
        task_id = created.json()["task_id"]

        dispatched = client.post("/internal/dispatch/run-once", headers=ADMIN)
        assert dispatched.status_code == 200
        assert dispatched.json()["dispatched"] is False
        assert dispatched.json()["reason"] == "CAPACITY_UNAVAILABLE"

        status = client.get(f"/v1/video-generations/{task_id}", headers=AUTH).json()
        assert status["status"] == "queued"
        assert status["error"] == "CAPACITY_UNAVAILABLE"

        admin_tasks = client.get("/admin/tasks", params={"error_code": "CAPACITY_UNAVAILABLE"}, headers=ADMIN)
        assert admin_tasks.status_code == 200
        assert [item["task_id"] for item in admin_tasks.json()] == [task_id]

        metrics = client.get("/metrics").text
        assert 'ltx_task_failures_total{error_code="CAPACITY_UNAVAILABLE"} 1' in metrics


def test_gpu_worker_dispatch_assigns_matching_idle_worker_once(tmp_path):
    with _gpu_client(tmp_path) as client:
        quality_worker = client.post(
            "/internal/workers/register",
            json=_worker_payload(0, profiles=["quality"]),
            headers=WORKER,
        ).json()
        fast_worker = client.post(
            "/internal/workers/register",
            json=_worker_payload(1, profiles=["fast"]),
            headers=WORKER,
        ).json()

        created = client.post("/v1/video-generations", json=_text_payload(prompt="dispatch gpu"), headers=AUTH)
        task_id = created.json()["task_id"]

        dispatched = client.post("/internal/dispatch/run-once", headers=ADMIN)
        assert dispatched.status_code == 200
        assert dispatched.json()["dispatched"] is True
        attempt_id = dispatched.json()["attempt_id"]
        assert dispatched.json()["worker_id"] == fast_worker["worker_id"]

        duplicate = client.post("/internal/dispatch/run-once", headers=ADMIN)
        assert duplicate.status_code == 200
        assert duplicate.json()["dispatched"] is False

        status = client.get(f"/v1/video-generations/{task_id}", headers=AUTH).json()
        assert status["status"] == "running"
        assert status["attempt_count"] == 1

        mock_complete = client.post("/internal/dispatch/complete-running", headers=ADMIN)
        assert mock_complete.status_code == 200
        assert mock_complete.json()["completed"] is False
        still_running = client.get(f"/v1/video-generations/{task_id}", headers=AUTH).json()
        assert still_running["status"] == "running"

        with client.app.state.ltx.session_factory() as session:
            from ltx_service.models import TaskAttempt

            attempts = session.query(TaskAttempt).filter_by(task_id=task_id).all()
            assert len(attempts) == 1
            assert attempts[0].id == attempt_id
            assert attempts[0].worker_id == fast_worker["worker_id"]

        workers = client.get("/admin/workers", headers=ADMIN).json()["workers"]
        by_id = {item["worker_id"]: item for item in workers}
        assert by_id[fast_worker["worker_id"]]["status"] == "busy"
        assert by_id[fast_worker["worker_id"]]["current_attempt_id"] == attempt_id
        assert by_id[quality_worker["worker_id"]]["status"] == "idle"


def test_gpu_worker_dispatch_matches_ultra_profile_and_records_gpu_seconds(tmp_path, monkeypatch):
    captured: dict = {}

    class FakeResponse:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"status":"accepted"}'

    def fake_urlopen(request, timeout=0):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with _gpu_client(tmp_path) as client:
        fast_worker = _worker_payload(0, profiles=["fast"])
        fast_worker["capabilities"]["gpu_count"] = 1
        client.post("/internal/workers/register", json=fast_worker, headers=WORKER)
        ultra_worker = _worker_payload(2, profiles=["ultra"])
        ultra_worker["worker_name"] = "gpu-host-01-ultra"
        ultra_worker["capabilities"]["gpu_indices"] = [2, 3]
        ultra_worker["capabilities"]["gpu_count"] = 2
        ultra_worker["capabilities"]["assign_url"] = "http://worker-ultra:9000/worker/attempts"
        registered_ultra = client.post("/internal/workers/register", json=ultra_worker, headers=WORKER).json()

        created = client.post(
            "/v1/video-generations",
            json=_text_payload(prompt="dispatch ultra", profile="ultra"),
            headers=AUTH,
        )
        assert created.status_code == 200
        task_id = created.json()["task_id"]

        dispatched = client.post("/internal/dispatch/run-once", headers=ADMIN)
        assert dispatched.status_code == 200
        assert dispatched.json()["worker_id"] == registered_ultra["worker_id"]
        attempt_id = dispatched.json()["attempt_id"]
        assert captured["payload"]["profile"] == "ultra"

        output_uri = captured["payload"]["output"]["storage_uri"]
        client.app.state.ltx.storage.write_bytes(output_uri, b"ultra video")
        completed = client.post(
            f"/internal/attempts/{attempt_id}/events",
            json={
                "status": "succeeded",
                "output_storage_uri": output_uri,
                "output_size_bytes": len(b"ultra video"),
                "runtime_seconds": 9,
            },
            headers=WORKER,
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "succeeded"

        usage = client.get("/admin/usage", headers=ADMIN).json()[0]
        assert usage["actual_runtime_seconds"] == 9
        assert usage["actual_gpu_seconds"] == 18
        assert usage["estimated_gpu_seconds"] == created.json()["estimated_gpu_seconds"]


def test_gpu_worker_dispatch_retryable_assign_failure_requeues(tmp_path):
    with _gpu_client(tmp_path) as client:
        worker = client.post("/internal/workers/register", json=_worker_payload(0), headers=WORKER).json()
        created = client.post(
            "/v1/video-generations",
            json=_text_payload(prompt="ASSIGN_TRANSIENT then retry"),
            headers=AUTH,
        )
        task_id = created.json()["task_id"]

        dispatched = client.post("/internal/dispatch/run-once", headers=ADMIN)
        assert dispatched.status_code == 200
        assert dispatched.json()["dispatched"] is False
        assert dispatched.json()["reason"] == "COMFYUI_PROMPT_FAILED"
        assert dispatched.json()["attempt_id"].startswith("att_")

        status = client.get(f"/v1/video-generations/{task_id}", headers=AUTH).json()
        assert status["status"] == "queued"
        assert status["attempt_count"] == 1
        assert status["error"] == "COMFYUI_PROMPT_FAILED"

        workers = client.get("/admin/workers", headers=ADMIN).json()["workers"]
        assert workers[0]["worker_id"] == worker["worker_id"]
        assert workers[0]["status"] == "idle"
        assert workers[0]["current_attempt_id"] is None


def test_gpu_worker_dispatch_non_retryable_assign_failure_fails_task(tmp_path):
    with _gpu_client(tmp_path) as client:
        client.post("/internal/workers/register", json=_worker_payload(0), headers=WORKER)
        created = client.post(
            "/v1/video-generations",
            json=_text_payload(prompt="ASSIGN_INVALID"),
            headers=AUTH,
        )
        task_id = created.json()["task_id"]

        dispatched = client.post("/internal/dispatch/run-once", headers=ADMIN)
        assert dispatched.status_code == 200
        assert dispatched.json()["dispatched"] is False
        assert dispatched.json()["reason"] == "REQUEST_INVALID_PARAMETER"

        status = client.get(f"/v1/video-generations/{task_id}", headers=AUTH).json()
        assert status["status"] == "failed"
        assert status["attempt_count"] == 1
        assert status["error"] == "REQUEST_INVALID_PARAMETER"

        usage = client.get("/admin/usage", headers=ADMIN).json()
        assert usage[0]["failed_count"] == 1
        assert usage[0]["attempt_count"] == 1


def test_gpu_worker_assignment_http_and_completion_event_succeeds(tmp_path, monkeypatch):
    captured: dict = {}

    class FakeResponse:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"status":"accepted"}'

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with _gpu_client(tmp_path) as client:
        worker_payload = _worker_payload(0)
        worker_payload["capabilities"]["assign_url"] = "http://worker-0:9000/worker/attempts"
        worker = client.post("/internal/workers/register", json=worker_payload, headers=WORKER).json()

        created = client.post("/v1/video-generations", json=_text_payload(prompt="real worker path"), headers=AUTH)
        task_id = created.json()["task_id"]

        dispatched = client.post("/internal/dispatch/run-once", headers=ADMIN)
        assert dispatched.status_code == 200
        assert dispatched.json()["dispatched"] is True
        attempt_id = dispatched.json()["attempt_id"]
        assert captured["url"] == "http://worker-0:9000/worker/attempts"
        assert captured["payload"]["attempt_id"] == attempt_id
        assert captured["payload"]["task_id"] == task_id
        output_uri = captured["payload"]["output"]["storage_uri"]
        assert output_uri.startswith("local://outputs/")

        client.app.state.ltx.storage.write_bytes(output_uri, b"gpu video bytes")
        completed = client.post(
            f"/internal/attempts/{attempt_id}/events",
            json={
                "status": "succeeded",
                "output_storage_uri": output_uri,
                "output_content_type": "video/mp4",
                "output_size_bytes": len(b"gpu video bytes"),
                "runtime_seconds": 9,
            },
            headers=WORKER,
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "succeeded"

        result = client.get(f"/v1/video-generations/{task_id}/result", headers=AUTH)
        assert result.status_code == 200
        asset_url = result.json()["outputs"][0]["download_url"]
        asset_id = asset_url.rsplit("/", 2)[-2]
        content = client.get(f"/v1/assets/{asset_id}/content", headers=AUTH)
        assert content.content == b"gpu video bytes"

        workers = client.get("/admin/workers", headers=ADMIN).json()["workers"]
        assert workers[0]["worker_id"] == worker["worker_id"]
        assert workers[0]["status"] == "idle"
        assert workers[0]["current_attempt_id"] is None


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
    assert {item["profile"] for item in payload["profiles"]} == {"fast", "ultra", "vip", "quality"}

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


def _text_payload(prompt: str = "hello", profile: str = "fast") -> dict:
    return {
        "mode": "text_to_video",
        "prompt": prompt,
        "profile": profile,
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


def _worker_payload(gpu_index: int, profiles: list[str] | None = None) -> dict:
    return {
        "node_name": "gpu-host-01",
        "worker_name": f"gpu-host-01-gpu-{gpu_index}",
        "gpu_index": gpu_index,
        "worker_slot": gpu_index,
        "status": "idle",
        "queue_depth": 0,
        "capabilities": {
            "modes": ["text_to_video", "image_to_video"],
            "profiles": profiles or ["fast"],
            "ltx_profile": "distilled_single_stage",
            "gpu_indices": [gpu_index],
            "gpu_count": 1,
        },
        "metrics_url": f"http://gpu-host-01:{9100 + gpu_index}/metrics",
    }


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


def _gpu_client(tmp_path):
    from ltx_service.app import create_app
    from ltx_service.config import Settings

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'gpu.db'}",
        storage_root=tmp_path / "objects",
        executor_backend="gpu-worker",
        bootstrap_api_key=API_KEY,
        admin_token=ADMIN_TOKEN,
        worker_token=WORKER_TOKEN,
    )
    return TestClient(create_app(settings))
