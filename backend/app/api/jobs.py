import os
import re
import zipfile
import tempfile
import csv
import io
from datetime import datetime, timezone
from email_validator import validate_email, EmailNotValidError
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Header, UploadFile, File, Form
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from app import schemas, models
from app.db import get_db
from app.worker.processor import process_job
from app.config import settings
from app.security import require_api_key

router = APIRouter(dependencies=[Depends(require_api_key)])


def _validate_recipient(name: str, email: str):
    """
    Returns (error_code, error_message) or (None, None) if valid.
    Kept separate so it is easily unit-testable.
    """
    stripped_name = name.strip()
    if not stripped_name:
        return "INVALID_NAME", "Name must not be blank"
    if len(stripped_name) > 100:
        return "INVALID_NAME", f"Name exceeds 100 characters (got {len(stripped_name)})"
    try:
        validate_email(email, check_deliverability=False)
    except EmailNotValidError as exc:
        return "INVALID_EMAIL", str(exc)
    return None, None


@router.post("", status_code=202)
def create_job(
    job_in: schemas.JobCreate,
    background_tasks: BackgroundTasks,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    # --- Idempotency: return existing job if key already seen ---
    if idempotency_key:
        existing = db.query(models.GenerationJob).filter(
            models.GenerationJob.idempotency_key == idempotency_key
        ).first()
        if existing:
            accepted = db.query(func.count(models.CertificateRecord.id)).filter(
                models.CertificateRecord.job_id == existing.id,
                models.CertificateRecord.status != models.RecordStatus.FAILED,
            ).scalar() or 0
            rejected = existing.total - accepted
            return Response(
                content=schemas.JobResponse(
                    id=existing.id,
                    title=existing.title,
                    status=existing.status,
                    total=existing.total,
                    accepted=accepted,
                    rejected=rejected,
                    created_at=existing.created_at,
                ).model_dump_json(),
                status_code=200,
                media_type="application/json",
                headers={"Location": f"/api/v1/jobs/{existing.id}"},
            )

    # --- Create the job row ---
    db_job = models.GenerationJob(
        title=job_in.title,
        event_name=job_in.event_name,
        issue_date=job_in.issue_date,
        total=len(job_in.recipients),
        idempotency_key=idempotency_key,
    )
    db.add(db_job)
    db.commit()
    db.refresh(db_job)

    accepted = 0
    rejected = 0

    # --- Per-recipient validation ---
    for idx, recipient in enumerate(job_in.recipients):
        error_code, error_message = _validate_recipient(recipient.name, recipient.email)

        if error_code:
            # Store invalid record immediately as FAILED so it is traceable
            record = models.CertificateRecord(
                job_id=db_job.id,
                row_index=idx,
                name=recipient.name,
                email=recipient.email,
                status=models.RecordStatus.FAILED,
                error_code=error_code,
                error_message=error_message,
            )
            rejected += 1
        else:
            record = models.CertificateRecord(
                job_id=db_job.id,
                row_index=idx,
                name=recipient.name.strip(),
                email=recipient.email.strip(),
                status=models.RecordStatus.PENDING,
            )
            accepted += 1

        db.add(record)

    db.commit()

    # If every recipient failed validation, finalize job without dispatching
    if accepted == 0:
        db_job.status = models.JobStatus.FAILED
        db.commit()
    else:
        background_tasks.add_task(process_job, db_job.id)

    response_body = schemas.JobResponse(
        id=db_job.id,
        title=db_job.title,
        status=db_job.status,
        total=db_job.total,
        accepted=accepted,
        rejected=rejected,
        created_at=db_job.created_at,
    ).model_dump_json()

    return Response(
        content=response_body,
        status_code=202,
        media_type="application/json",
        headers={"Location": f"/api/v1/jobs/{db_job.id}"},
    )


@router.post("/upload", status_code=202)
def upload_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(...),
    event_name: Optional[str] = Form(None),
    issue_date: Optional[str] = Form(None),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    content = file.file.read(settings.CSV_MAX_BYTES + 1)
    if len(content) > settings.CSV_MAX_BYTES:
        raise HTTPException(status_code=413, detail="CSV file is too large")

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="CSV must be UTF-8 encoded")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or set(reader.fieldnames) != {"name", "email"}:
        raise HTTPException(status_code=422, detail="CSV must contain name and email columns")

    recipients = []
    for row in reader:
        recipients.append(
            schemas.RecipientCreate(
                name=row.get("name") or "",
                email=row.get("email") or "",
            )
        )

    try:
        job_in = schemas.JobCreate(
            title=title,
            event_name=event_name,
            issue_date=issue_date,
            recipients=recipients,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return create_job(job_in, background_tasks, idempotency_key, db)


@router.get("/{job_id}/recipients", response_model=List[schemas.RecordResponse])
def list_job_recipients(
    job_id: str,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    if not db.query(models.GenerationJob).filter(models.GenerationJob.id == job_id).first():
        raise HTTPException(status_code=404, detail="Job not found")

    limit = min(limit, 200)  # cap at 200 per spec

    q = db.query(models.CertificateRecord).filter(models.CertificateRecord.job_id == job_id)
    if status:
        q = q.filter(models.CertificateRecord.status == status.upper())
    q = q.order_by(models.CertificateRecord.row_index)
    return q.offset(offset).limit(limit).all()


@router.get("/{job_id}", response_model=schemas.JobStatusResponse)
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    job = db.query(models.GenerationJob).filter(models.GenerationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Derive counts with GROUP BY — never trust stored counters
    rows = (
        db.query(models.CertificateRecord.status, func.count(models.CertificateRecord.id))
        .filter(models.CertificateRecord.job_id == job_id)
        .group_by(models.CertificateRecord.status)
        .all()
    )
    counts = {status: count for status, count in rows}
    succeeded = counts.get("SUCCESS", 0)
    failed = counts.get("FAILED", 0)
    pending = counts.get("PENDING", 0)
    processing = counts.get("PROCESSING", 0)
    processed = succeeded + failed  # pending + processing = not yet done

    percent_complete = (processed / job.total * 100) if job.total > 0 else 0.0

    return schemas.JobStatusResponse(
        id=job.id,
        title=job.title,
        status=job.status,
        total=job.total,
        processed=processed,
        succeeded=succeeded,
        failed=failed,
        pending=pending,
        percent_complete=round(percent_complete, 2),
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.get("/{job_id}/download-all")
def download_all_certificates(job_id: str, db: Session = Depends(get_db)):
    if not db.query(models.GenerationJob).filter(models.GenerationJob.id == job_id).first():
        raise HTTPException(status_code=404, detail="Job not found")

    records = db.query(models.CertificateRecord).filter(
        models.CertificateRecord.job_id == job_id,
        models.CertificateRecord.status == models.RecordStatus.SUCCESS,
    ).all()

    if not records:
        # Documented decision: 409 when job exists but nothing succeeded yet
        raise HTTPException(
            status_code=409,
            detail="No successful certificates ready yet. Poll /api/v1/jobs/{id} and retry when succeeded > 0.",
        )

    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    with zipfile.ZipFile(temp_zip.name, "w") as zipf:
        for record in records:
            if record.file_path and os.path.exists(record.file_path):
                # Use certificate_code as filename — never raw user input
                arcname = f"{record.certificate_code}.pdf"
                zipf.write(record.file_path, arcname=arcname)

    return FileResponse(
        temp_zip.name,
        media_type="application/zip",
        filename=f"certificates_{job_id}.zip",
    )


@router.get("/certificates/{certificate_code}/download")
def download_certificate(certificate_code: str, db: Session = Depends(get_db)):
    record = db.query(models.CertificateRecord).filter(
        models.CertificateRecord.certificate_code == certificate_code
    ).first()

    if not record:
        raise HTTPException(status_code=404, detail="Certificate not found")

    # 409 means "found but not ready" — distinct from 404 "never existed"
    if record.status != models.RecordStatus.SUCCESS:
        raise HTTPException(
            status_code=409,
            detail=f"Certificate is not ready yet (status: {record.status})",
        )

    if not record.file_path or not os.path.exists(record.file_path):
        raise HTTPException(status_code=404, detail="Certificate file missing on disk")

    return FileResponse(
        record.file_path,
        media_type="application/pdf",
        filename=f"{record.certificate_code}.pdf",  # safe filename
    )


@router.post("/{job_id}/retry", response_model=schemas.JobStatusResponse)
def retry_failed_certificates(
    job_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Reset only records that failed during rendering (error_code=RENDER_ERROR) back
    to PENDING and re-dispatch processing.  Validation failures (INVALID_EMAIL /
    INVALID_NAME) are left alone — re-submitting bad data would produce the same result.
    Returns 409 if the job is still actively PROCESSING.
    """
    job = db.query(models.GenerationJob).filter(models.GenerationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status == models.JobStatus.PROCESSING:
        raise HTTPException(status_code=409, detail="Job is still processing; wait for it to finish before retrying")

    render_failures = (
        db.query(models.CertificateRecord)
        .filter(
            models.CertificateRecord.job_id == job_id,
            models.CertificateRecord.error_code == "RENDER_ERROR",
        )
        .all()
    )

    if not render_failures:
        raise HTTPException(status_code=409, detail="No render-failed records to retry")

    for record in render_failures:
        record.status = models.RecordStatus.PENDING
        record.error_code = None
        record.error_message = None
        record.file_path = None
        record.completed_at = None

    job.status = models.JobStatus.PENDING
    db.commit()

    background_tasks.add_task(process_job, job_id)

    # Return current status (counts reflect the reset)
    return get_job_status(job_id, db)


@router.post("/{job_id}/cancel", response_model=schemas.JobStatusResponse)
def cancel_job(
    job_id: str,
    db: Session = Depends(get_db),
):
    """Cancel a pending or active job before all records finish rendering."""
    job = db.query(models.GenerationJob).filter(models.GenerationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in (models.JobStatus.PENDING, models.JobStatus.PROCESSING):
        raise HTTPException(
            status_code=409,
            detail=f"Job cannot be cancelled from status {job.status}",
        )

    job.status = models.JobStatus.CANCELLED
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    return get_job_status(job_id, db)
