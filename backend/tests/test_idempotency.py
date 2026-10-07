"""
test_idempotency.py — tests for the Idempotency-Key header.
"""
from app.worker.processor import process_job


def test_same_idempotency_key_returns_same_job(client, db):
    headers = {"Idempotency-Key": "unique-key-abc"}
    payload = {
        "title": "Idempotency Test",
        "recipients": [{"name": "Alice", "email": "alice@example.com"}],
    }

    r1 = client.post("/api/v1/jobs", json=payload, headers=headers)
    assert r1.status_code == 202
    job_id_1 = r1.json()["id"]

    r2 = client.post("/api/v1/jobs", json=payload, headers=headers)
    # Second call returns 200 (already exists) with same job_id
    assert r2.status_code == 200
    job_id_2 = r2.json()["id"]

    assert job_id_1 == job_id_2


def test_no_duplicate_records_on_repeated_key(client, db):
    session, _, _ = db
    from app import models
    headers = {"Idempotency-Key": "no-dup-key"}
    payload = {
        "title": "No Dup Test",
        "recipients": [{"name": "Alice", "email": "alice@example.com"}],
    }
    client.post("/api/v1/jobs", json=payload, headers=headers)
    client.post("/api/v1/jobs", json=payload, headers=headers)

    count = session.query(models.GenerationJob).count()
    assert count == 1
