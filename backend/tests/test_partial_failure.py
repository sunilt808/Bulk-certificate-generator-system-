"""
test_partial_failure.py — test that one failing record doesn't block others.
"""
import pytest
from app import models
from app.worker.processor import process_job


def test_partial_failure_ends_completed_with_errors(client, db, monkeypatch):
    session, _, _ = db
    from app.rendering import renderer as renderer_mod
    orig = renderer_mod.generate_certificate

    def selective_fail(name, *args, **kwargs):
        if name == "FailName":
            raise RuntimeError("intentional render failure")
        return orig(name, *args, **kwargs)

    monkeypatch.setattr("app.worker.processor.generate_certificate", selective_fail)

    r = client.post("/api/v1/jobs", json={
        "title": "Partial Fail Test",
        "recipients": [
            {"name": "GoodName", "email": "good@example.com"},
            {"name": "FailName", "email": "fail@example.com"},
        ],
    })
    assert r.status_code == 202
    job_id = r.json()["id"]

    process_job(job_id)  # synchronous in test

    status = client.get(f"/api/v1/jobs/{job_id}").json()
    assert status["status"] == "COMPLETED_WITH_ERRORS"
    assert status["succeeded"] == 1
    assert status["failed"] == 1

    recs = client.get(f"/api/v1/jobs/{job_id}/recipients").json()
    by_name = {r["name"]: r for r in recs}

    assert by_name["GoodName"]["status"] == "SUCCESS"
    assert by_name["FailName"]["status"] == "FAILED"
    assert by_name["FailName"]["error_code"] == "RENDER_ERROR"
    assert "intentional render failure" in by_name["FailName"]["error_message"]

    # Job must not be stuck in PROCESSING
    assert status["status"] != "PROCESSING"


def test_partial_failure_retry_resets_render_errors(client, db, monkeypatch):
    session, _, _ = db
    from app.rendering import renderer as renderer_mod
    orig = renderer_mod.generate_certificate
    fail_flag = {"active": True}

    def selective_fail(name, *args, **kwargs):
        if name == "FailName" and fail_flag["active"]:
            raise RuntimeError("intentional fail")
        return orig(name, *args, **kwargs)

    monkeypatch.setattr("app.worker.processor.generate_certificate", selective_fail)

    r = client.post("/api/v1/jobs", json={
        "title": "Retry Test",
        "recipients": [
            {"name": "GoodName", "email": "good@example.com"},
            {"name": "FailName", "email": "fail@example.com"},
        ],
    })
    job_id = r.json()["id"]
    process_job(job_id)

    status = client.get(f"/api/v1/jobs/{job_id}").json()
    assert status["status"] == "COMPLETED_WITH_ERRORS"

    # Now turn off the failure and retry
    fail_flag["active"] = False
    retry_r = client.post(f"/api/v1/jobs/{job_id}/retry")
    assert retry_r.status_code == 200

    process_job(job_id)  # process the reset PENDING records

    final = client.get(f"/api/v1/jobs/{job_id}").json()
    assert final["succeeded"] == 2


def test_retry_409_when_still_processing(client, db):
    session, _, _ = db
    r = client.post("/api/v1/jobs", json={
        "title": "Retry 409 Test",
        "recipients": [{"name": "Alice", "email": "alice@example.com"}],
    })
    job_id = r.json()["id"]
    # Manually set job to PROCESSING
    job = session.query(models.GenerationJob).filter_by(id=job_id).first()
    job.status = models.JobStatus.PROCESSING
    session.commit()

    r2 = client.post(f"/api/v1/jobs/{job_id}/retry")
    assert r2.status_code == 409


def test_retry_409_no_render_failures(client, db):
    """Retry on a job with only validation failures should 409."""
    r = client.post("/api/v1/jobs", json={
        "title": "Val Fail Job",
        "recipients": [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "", "email": "bad"},  # validation failure
        ],
    })
    job_id = r.json()["id"]
    process_job(job_id)
    # The FAILED record has error_code=INVALID_NAME, not RENDER_ERROR
    r2 = client.post(f"/api/v1/jobs/{job_id}/retry")
    assert r2.status_code == 409
