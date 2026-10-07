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


def test_reprocessing_completed_job_does_not_render_again(client, db, monkeypatch):
    session, _, _ = db
    job = models.GenerationJob(title="Claim Job", total=1)
    session.add(job)
    session.flush()
    record = models.CertificateRecord(
        job_id=job.id,
        row_index=0,
        name="Claimed User",
        email="claimed@example.com",
        status=models.RecordStatus.PENDING,
    )
    session.add(record)
    session.commit()

    calls = []

    def fake_generate(*args):
        calls.append(args)
        return "certificate.pdf"

    monkeypatch.setattr("app.worker.processor.generate_certificate", fake_generate)
    process_job(job.id)
    process_job(job.id)

    assert len(calls) == 1


def test_large_job_is_processed_in_batches(client, db, monkeypatch):
    session, _, _ = db
    job = models.GenerationJob(title="Batch Job", total=5)
    session.add(job)
    session.flush()
    for row_index in range(5):
        session.add(
            models.CertificateRecord(
                job_id=job.id,
                row_index=row_index,
                name=f"User {row_index}",
                email=f"user{row_index}@example.com",
                status=models.RecordStatus.PENDING,
            )
        )
    session.commit()

    monkeypatch.setattr("app.worker.processor.settings.PROCESSING_BATCH_SIZE", 2)
    monkeypatch.setattr(
        "app.worker.processor.generate_certificate",
        lambda *args: "certificate.pdf",
    )

    process_job(job.id)

    assert session.query(models.CertificateRecord).filter_by(
        job_id=job.id, status=models.RecordStatus.SUCCESS
    ).count() == 5
