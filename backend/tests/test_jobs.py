"""
test_jobs.py — tests for job creation, per-recipient validation, and status.
"""
import pytest
from app import models
from app.worker.processor import process_job


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_job(client, recipients, **kwargs):
    payload = {"title": "Test Job", "recipients": recipients, **kwargs}
    return client.post("/api/v1/jobs", json=payload)


def wait_for_done(client, job_id):
    """Call process_job synchronously via the test client's DB."""
    # We call the endpoint to get job_id, then call the processor directly.
    pass  # processor is called inline in tests that need it


# ---------------------------------------------------------------------------
# Task 1 — Job creation and Location header
# ---------------------------------------------------------------------------

def test_create_job_returns_202_with_location(client):
    r = make_job(client, [
        {"name": "Alice", "email": "alice@example.com"},
        {"name": "Bob", "email": "bob@example.com"},
    ])
    assert r.status_code == 202
    data = r.json()
    assert "id" in data
    assert data["total"] == 2
    assert data["accepted"] == 2
    assert data["rejected"] == 0
    assert "Location" in r.headers
    assert data["id"] in r.headers["Location"]


def test_create_job_mixed_valid_invalid(client, db):
    session, TestingSession, _ = db
    r = make_job(client, [
        {"name": "Alice", "email": "alice@example.com"},
        {"name": "", "email": "alice@example.com"},       # blank name
        {"name": "Bob", "email": "not-an-email"},          # bad email
    ])
    assert r.status_code == 202
    data = r.json()
    assert data["accepted"] == 1
    assert data["rejected"] == 2
    assert data["total"] == 3


# ---------------------------------------------------------------------------
# Task 1 — Envelope-level validation still returns 422
# ---------------------------------------------------------------------------

def test_empty_recipient_list_returns_422(client):
    r = make_job(client, [])
    assert r.status_code == 422


def test_missing_title_returns_422(client):
    r = client.post("/api/v1/jobs", json={
        "recipients": [{"name": "A", "email": "a@a.com"}]
    })
    assert r.status_code == 422


def test_over_limit_returns_422(client, monkeypatch):
    # Monkeypatch settings.MAX_RECIPIENTS_PER_JOB would require schema change;
    # instead verify the Field(max_length=1000) via 1001 items.
    recipients = [{"name": f"User{i}", "email": f"u{i}@x.com"} for i in range(1001)]
    r = make_job(client, recipients)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Task 1 — Per-recipient validation errors stored as FAILED records
# ---------------------------------------------------------------------------

def test_blank_name_stored_as_failed(client):
    r = make_job(client, [{"name": "   ", "email": "ok@example.com"}])
    job_id = r.json()["id"]
    recs = client.get(f"/api/v1/jobs/{job_id}/recipients").json()
    assert recs[0]["status"] == "FAILED"
    assert recs[0]["error_code"] == "INVALID_NAME"


def test_long_name_stored_as_failed(client):
    r = make_job(client, [{"name": "A" * 101, "email": "ok@example.com"}])
    job_id = r.json()["id"]
    recs = client.get(f"/api/v1/jobs/{job_id}/recipients").json()
    assert recs[0]["status"] == "FAILED"
    assert recs[0]["error_code"] == "INVALID_NAME"


def test_bad_email_stored_as_failed(client):
    r = make_job(client, [{"name": "John", "email": "not-an-email"}])
    job_id = r.json()["id"]
    recs = client.get(f"/api/v1/jobs/{job_id}/recipients").json()
    assert recs[0]["status"] == "FAILED"
    assert recs[0]["error_code"] == "INVALID_EMAIL"


def test_all_invalid_job_finalized_as_failed(client):
    r = make_job(client, [{"name": "", "email": "bad"}])
    data = r.json()
    assert data["status"] == "FAILED"  # immediately finalized, no processing


# ---------------------------------------------------------------------------
# Task 2 — Job status / progress
# ---------------------------------------------------------------------------

def test_job_status_after_processing(client, db, tmp_path):
    session, TestingSession, _ = db
    r = make_job(client, [{"name": "Alice", "email": "alice@example.com"}])
    job_id = r.json()["id"]

    process_job(job_id)  # run synchronously in test

    status = client.get(f"/api/v1/jobs/{job_id}").json()
    assert status["status"] == "COMPLETED"
    assert status["succeeded"] == 1
    assert status["failed"] == 0
    assert status["pending"] == 0
    assert status["percent_complete"] == 100.0
    assert status["started_at"] is not None
    assert status["finished_at"] is not None


def test_job_status_intermediate(client, db):
    """Manually create records in mixed statuses to verify derived counts."""
    session, TestingSession, _ = db

    # Create the job directly in the DB without going through the endpoint
    # so we fully control what records exist.
    job = models.GenerationJob(title="Intermediate Test", total=4, status=models.JobStatus.PROCESSING)
    session.add(job)
    session.flush()

    for i, (name, status) in enumerate([
        ("S1", "SUCCESS"),
        ("S2", "SUCCESS"),
        ("F1", "FAILED"),
        ("P1", "PENDING"),
    ]):
        rec = models.CertificateRecord(
            job_id=job.id, row_index=i, name=name, email=f"{name}@x.com",
            status=status,
        )
        session.add(rec)
    session.commit()

    status_data = client.get(f"/api/v1/jobs/{job.id}").json()
    assert status_data["succeeded"] == 2
    assert status_data["failed"] == 1
    assert status_data["pending"] == 1
    # processed = succeeded + failed
    assert status_data["processed"] == 3
    assert status_data["percent_complete"] == pytest.approx(75.0)


# ---------------------------------------------------------------------------
# Task 3 — Recipients listing filters
# ---------------------------------------------------------------------------

def test_recipients_filter_by_status(client, db):
    session, _, _ = db
    r = make_job(client, [
        {"name": "Good", "email": "good@example.com"},
        {"name": "", "email": "bad"},
    ])
    job_id = r.json()["id"]
    process_job(job_id)

    failed = client.get(f"/api/v1/jobs/{job_id}/recipients?status=FAILED").json()
    assert all(rec["status"] == "FAILED" for rec in failed)


def test_recipients_ordered_by_row_index(client, db):
    session, _, _ = db
    recipients = [{"name": f"User{i}", "email": f"u{i}@x.com"} for i in range(5)]
    r = make_job(client, recipients)
    job_id = r.json()["id"]
    recs = client.get(f"/api/v1/jobs/{job_id}/recipients").json()
    indices = [rec["row_index"] for rec in recs]
    assert indices == sorted(indices)


def test_recipients_limit_and_offset(client, db):
    session, _, _ = db
    recipients = [{"name": f"User{i}", "email": f"u{i}@x.com"} for i in range(10)]
    r = make_job(client, recipients)
    job_id = r.json()["id"]
    page1 = client.get(f"/api/v1/jobs/{job_id}/recipients?limit=3&offset=0").json()
    page2 = client.get(f"/api/v1/jobs/{job_id}/recipients?limit=3&offset=3").json()
    assert len(page1) == 3
    assert len(page2) == 3
    assert page1[0]["row_index"] != page2[0]["row_index"]
