from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import update
from app.db import SessionLocal
from app import models
from app.config import settings
from app.rendering.renderer import generate_certificate


def process_job(job_id: str) -> None:
    """
    Process all PENDING records for a job.

    Idempotent: records already SUCCESS are skipped, so this can be called
    again safely after a crash (startup recovery).
    """
    db: Session = SessionLocal()
    try:
        job = db.query(models.GenerationJob).filter(models.GenerationJob.id == job_id).first()
        if not job:
            return

        # Only move to PROCESSING if not already there (idempotency guard)
        if job.status not in (models.JobStatus.PROCESSING, models.JobStatus.PENDING):
            return

        job.status = models.JobStatus.PROCESSING
        if not job.started_at:
            job.started_at = datetime.now(timezone.utc)
        db.commit()

        has_failures = False

        while True:
            db.refresh(job)
            if job.status == models.JobStatus.CANCELLED:
                return

            records = (
                db.query(models.CertificateRecord)
                .filter(
                    models.CertificateRecord.job_id == job_id,
                    models.CertificateRecord.status == models.RecordStatus.PENDING,
                )
                .order_by(models.CertificateRecord.row_index)
                .limit(settings.PROCESSING_BATCH_SIZE)
                .all()
            )
            if not records:
                break

            claimed_records = []
            for record in records:
                claim = (
                    update(models.CertificateRecord)
                    .where(
                        models.CertificateRecord.id == record.id,
                        models.CertificateRecord.status == models.RecordStatus.PENDING,
                    )
                    .values(status=models.RecordStatus.PROCESSING)
                )
                claimed = db.execute(claim).rowcount == 1
                if claimed:
                    claimed_records.append(record)
                db.commit()
                if claimed:
                    db.refresh(record)

            for record in claimed_records:
                try:
                    file_path = generate_certificate(
                        record.name, job.event_name, job.issue_date, record.certificate_code
                    )
                    record.status = models.RecordStatus.SUCCESS
                    record.file_path = file_path
                except Exception as exc:
                    record.status = models.RecordStatus.FAILED
                    if type(exc).__name__ == "UnsupportedCharactersError":
                        record.error_code = "UNSUPPORTED_CHARACTERS"
                    else:
                        record.error_code = "RENDER_ERROR"
                    record.error_message = str(exc)
                    has_failures = True
                finally:
                    record.completed_at = datetime.now(timezone.utc)
                    # Commit per-record so a crash mid-batch leaves partial results,
                    # not a rollback of all completed records.
                    db.commit()

        db.refresh(job)
        if job.status == models.JobStatus.CANCELLED:
            return

        # Check if any previously-failed validation records exist (not render failures)
        any_failed = (
            db.query(models.CertificateRecord)
            .filter(
                models.CertificateRecord.job_id == job_id,
                models.CertificateRecord.status == models.RecordStatus.FAILED,
            )
            .first()
        )

        job.status = (
            models.JobStatus.COMPLETED_WITH_ERRORS
            if (has_failures or any_failed)
            else models.JobStatus.COMPLETED
        )
        job.finished_at = datetime.now(timezone.utc)
        db.commit()

    finally:
        db.close()
