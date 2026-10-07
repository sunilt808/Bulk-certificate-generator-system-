"""
test_retrieval.py — tests for single download, ZIP download, and path traversal safety.
"""
import zipfile
import pytest
from app import models
from app.worker.processor import process_job


def make_job_and_process(client, db, recipients):
    session, TestingSession, _ = db
    r = client.post("/api/v1/jobs", json={
        "title": "Retrieval Test",
        "recipients": recipients,
    })
    assert r.status_code == 202
    job_id = r.json()["id"]
    process_job(job_id)
    return job_id


# ---------------------------------------------------------------------------
# Single certificate download
# ---------------------------------------------------------------------------

def test_single_download_200(client, db, tmp_path):
    job_id = make_job_and_process(client, db, [{"name": "Alice", "email": "alice@example.com"}])
    session, _, _ = db
    record = session.query(models.CertificateRecord).filter_by(job_id=job_id).first()

    r = client.get(f"/api/v1/jobs/certificates/{record.certificate_code}/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"


def test_single_download_404_unknown_code(client, db):
    r = client.get("/api/v1/jobs/certificates/CERT-DOESNOTEXIST/download")
    assert r.status_code == 404


def test_single_download_409_not_ready(client, db):
    """A record that exists but is not yet SUCCESS must return 409."""
    session, _, _ = db
    # Create the job and record directly — bypass the endpoint so no background task fires
    job = models.GenerationJob(title="Pending Job", total=1, status=models.JobStatus.PENDING)
    session.add(job)
    session.flush()
    record = models.CertificateRecord(
        job_id=job.id, row_index=0, name="Alice", email="alice@example.com",
        status=models.RecordStatus.PENDING,
    )
    session.add(record)
    session.commit()

    r = client.get(f"/api/v1/jobs/certificates/{record.certificate_code}/download")
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# ZIP download
# ---------------------------------------------------------------------------

def test_zip_contains_only_successful_records(client, db, tmp_path, monkeypatch):
    session, TestingSession, _ = db
    original_generate = None

    # Make one succeed and one fail via render error
    from app.rendering import renderer as renderer_mod
    orig = renderer_mod.generate_certificate

    def selective_fail(name, event_name, issue_date, cert_code):
        if name == "FailUser":
            raise RuntimeError("forced fail")
        return orig(name, event_name, issue_date, cert_code)

    monkeypatch.setattr("app.worker.processor.generate_certificate", selective_fail)

    r = client.post("/api/v1/jobs", json={
        "title": "ZIP Test",
        "recipients": [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "FailUser", "email": "fail@example.com"},
        ],
    })
    job_id = r.json()["id"]
    process_job(job_id)

    zip_r = client.get(f"/api/v1/jobs/{job_id}/download-all")
    assert zip_r.status_code == 200

    import io
    with zipfile.ZipFile(io.BytesIO(zip_r.content)) as zf:
        names = zf.namelist()
    # Only successful cert code in the zip, not FailUser's
    assert len(names) == 1
    assert names[0].endswith(".pdf")
    # Filename is certificate_code, not user name
    assert "FailUser" not in names[0]
    assert "Alice" not in names[0]


def test_zip_409_when_no_successes(client, db):
    """ZIP download on a job with no successful records yet returns 409."""
    session, _, _ = db
    job = models.GenerationJob(title="No Success", total=1, status=models.JobStatus.PENDING)
    session.add(job)
    session.flush()
    record = models.CertificateRecord(
        job_id=job.id, row_index=0, name="Alice", email="alice@example.com",
        status=models.RecordStatus.PENDING,
    )
    session.add(record)
    session.commit()

    r2 = client.get(f"/api/v1/jobs/{job.id}/download-all")
    assert r2.status_code == 409


def test_zip_404_unknown_job(client, db):
    r = client.get("/api/v1/jobs/doesnotexist/download-all")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Path traversal safety
# ---------------------------------------------------------------------------

def test_path_traversal_name_stored_safely(client, db, tmp_path):
    """
    A name like '../../etc/passwd' must not escape the media directory.
    The renderer uses UUID filenames, not user-supplied strings.
    """
    r = client.post("/api/v1/jobs", json={
        "title": "PathTraversal Test",
        "recipients": [{"name": "../../etc/passwd", "email": "hack@example.com"}],
    })
    job_id = r.json()["id"]
    process_job(job_id)

    session, _, _ = db
    record = session.query(models.CertificateRecord).filter_by(job_id=job_id).first()
    if record.status == models.RecordStatus.SUCCESS:
        # File must be inside tmp_path (the patched media dir)
        file_path = record.file_path
        resolved = str(tmp_path.resolve())
        assert file_path.startswith(resolved), f"Path escaped media dir: {file_path}"
