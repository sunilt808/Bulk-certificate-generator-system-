from app import models
from app.worker.processor import process_job


def test_pending_job_can_be_cancelled(client, db):
    session, _, _ = db
    job = models.GenerationJob(title="Cancel Job", total=1)
    session.add(job)
    session.flush()
    record = models.CertificateRecord(
        job_id=job.id,
        row_index=0,
        name="Pending User",
        email="pending@example.com",
    )
    session.add(record)
    session.commit()

    response = client.post(f"/api/v1/jobs/{job.id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    process_job(job.id)
    session.refresh(record)
    assert record.status == models.RecordStatus.PENDING


def test_completed_job_cannot_be_cancelled(client, db):
    session, _, _ = db
    job = models.GenerationJob(
        title="Completed Job",
        total=0,
        status=models.JobStatus.COMPLETED,
    )
    session.add(job)
    session.commit()

    response = client.post(f"/api/v1/jobs/{job.id}/cancel")

    assert response.status_code == 409
