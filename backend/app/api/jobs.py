from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List
from app import schemas, models
from app.db import get_db
from app.worker.processor import process_job

router = APIRouter()

@router.post("", response_model=schemas.JobResponse, status_code=202)
def create_job(job_in: schemas.JobCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    db_job = models.GenerationJob(
        title=job_in.title,
        event_name=job_in.event_name,
        issue_date=job_in.issue_date,
        total=len(job_in.recipients)
    )
    db.add(db_job)
    db.commit()
    db.refresh(db_job)
    
    for idx, recipient in enumerate(job_in.recipients):
        record = models.CertificateRecord(
            job_id=db_job.id,
            row_index=idx,
            name=recipient.name,
            email=recipient.email
        )
        db.add(record)
    
    db.commit()
    
    # Trigger background processing
    background_tasks.add_task(process_job, db_job.id)
    
    return db_job

@router.get("/{job_id}", response_model=schemas.JobStatusResponse)
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    job = db.query(models.GenerationJob).filter(models.GenerationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    records = db.query(models.CertificateRecord).filter(models.CertificateRecord.job_id == job_id).all()
    
    status_counts = {"SUCCESS": 0, "FAILED": 0, "PENDING": 0, "PROCESSING": 0}
    for r in records:
        if r.status in status_counts:
            status_counts[r.status] += 1
            
    progress = 0.0
    if job.total > 0:
        progress = ((status_counts["SUCCESS"] + status_counts["FAILED"]) / job.total) * 100
        
    return schemas.JobStatusResponse(
        id=job.id,
        title=job.title,
        status=job.status,
        total=job.total,
        created_at=job.created_at,
        succeeded_count=status_counts["SUCCESS"],
        failed_count=status_counts["FAILED"],
        pending_count=status_counts["PENDING"],
        processing_count=status_counts["PROCESSING"],
        progress_percentage=progress
    )

@router.get("/{job_id}/recipients", response_model=List[schemas.RecordResponse])
def list_job_recipients(job_id: str, db: Session = Depends(get_db)):
    records = db.query(models.CertificateRecord).filter(models.CertificateRecord.job_id == job_id).all()
    return records

import os
from fastapi.responses import FileResponse
import zipfile
import tempfile

@router.get("/{job_id}/download-all")
def download_all_certificates(job_id: str, db: Session = Depends(get_db)):
    job = db.query(models.GenerationJob).filter(models.GenerationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    records = db.query(models.CertificateRecord).filter(
        models.CertificateRecord.job_id == job_id,
        models.CertificateRecord.status == models.RecordStatus.SUCCESS
    ).all()
    
    if not records:
        raise HTTPException(status_code=404, detail="No successful certificates found to download")
        
    # Create a temporary zip file
    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    with zipfile.ZipFile(temp_zip.name, 'w') as zipf:
        for record in records:
            if record.file_path and os.path.exists(record.file_path):
                # Add file to zip, using the recipient's name for the filename
                arcname = f"{record.name.replace(' ', '_')}_{record.certificate_code}.pdf"
                zipf.write(record.file_path, arcname=arcname)
                
    return FileResponse(
        temp_zip.name,
        media_type="application/zip",
        filename=f"certificates_{job_id}.zip",
        background=None  # We should normally clean this up using a background task
    )

@router.get("/certificates/{certificate_code}/download")
def download_certificate(certificate_code: str, db: Session = Depends(get_db)):
    record = db.query(models.CertificateRecord).filter(models.CertificateRecord.certificate_code == certificate_code).first()
    if not record:
        raise HTTPException(status_code=404, detail="Certificate not found")
        
    if record.status != models.RecordStatus.SUCCESS or not record.file_path or not os.path.exists(record.file_path):
        raise HTTPException(status_code=404, detail="Certificate file not available")
        
    return FileResponse(
        record.file_path,
        media_type="application/pdf",
        filename=f"{record.name.replace(' ', '_')}_certificate.pdf"
    )
