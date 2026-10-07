from sqlalchemy.orm import Session
from app.db import SessionLocal
from app import models
from app.rendering.renderer import generate_certificate
from datetime import datetime, timezone

def process_job(job_id: str):
    db: Session = SessionLocal()
    try:
        job = db.query(models.GenerationJob).filter(models.GenerationJob.id == job_id).first()
        if not job:
            return

        job.status = models.JobStatus.PROCESSING
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        records = db.query(models.CertificateRecord).filter(
            models.CertificateRecord.job_id == job_id,
            models.CertificateRecord.status == models.RecordStatus.PENDING
        ).all()

        has_failures = False

        for record in records:
            record.status = models.RecordStatus.PROCESSING
            db.commit()

            try:
                # Monkey-patching point for tests: renderer should raise exception to test partial failures
                file_path = generate_certificate(record.name, job.event_name, job.issue_date)
                
                record.status = models.RecordStatus.SUCCESS
                record.file_path = file_path
            except Exception as e:
                record.status = models.RecordStatus.FAILED
                record.error_message = str(e)
                has_failures = True
            finally:
                record.completed_at = datetime.now(timezone.utc)
                db.commit()

        job.status = models.JobStatus.COMPLETED_WITH_ERRORS if has_failures else models.JobStatus.COMPLETED
        job.finished_at = datetime.now(timezone.utc)
        db.commit()

    finally:
        db.close()
