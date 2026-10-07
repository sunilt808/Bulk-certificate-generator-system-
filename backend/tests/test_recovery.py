"""
test_recovery.py — tests for startup crash recovery (Task 8).
"""
from app import models
from app.worker.processor import process_job


def test_stuck_processing_record_is_recovered(client, db, monkeypatch):
    """
    Simulate a crash: a record is left in PROCESSING state.
    The lifespan startup recovery resets it to PENDING.
    Then process_job picks it up and completes it.
    """
    session, TestingSession, _ = db

    # Create job and records manually
    job = models.GenerationJob(title="Crash Job", total=1, status=models.JobStatus.PROCESSING)
    session.add(job)
    session.flush()

    record = models.CertificateRecord(
        job_id=job.id,
        row_index=0,
        name="StuckUser",
        email="stuck@example.com",
        status=models.RecordStatus.PROCESSING,  # simulates crash mid-record
    )
    session.add(record)
    session.commit()

    # Simulate the startup recovery code
    stuck = session.query(models.CertificateRecord).filter_by(status="PROCESSING").all()
    for r in stuck:
        r.status = models.RecordStatus.PENDING
    jobs_to_retry = session.query(models.GenerationJob).filter_by(status="PROCESSING").all()
    for j in jobs_to_retry:
        j.status = models.JobStatus.PENDING
    session.commit()

    # Verify reset happened
    session.refresh(record)
    assert record.status == models.RecordStatus.PENDING

    # Now re-run the processor — it should complete the job
    process_job(job.id)

    session.refresh(job)
    assert job.status in (models.JobStatus.COMPLETED, models.JobStatus.COMPLETED_WITH_ERRORS)

    session.refresh(record)
    assert record.status == models.RecordStatus.SUCCESS
