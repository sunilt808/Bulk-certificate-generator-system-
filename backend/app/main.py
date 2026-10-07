from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.db import engine, Base, SessionLocal
from app.api import jobs, verify
from app import models


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup (no Alembic needed for this project)
    Base.metadata.create_all(bind=engine)

    # --- Startup recovery ---
    # If the server crashed mid-job, records may be stuck in PROCESSING.
    # Reset them to PENDING so they get retried.
    db = SessionLocal()
    try:
        stuck = (
            db.query(models.CertificateRecord)
            .filter(models.CertificateRecord.status == models.RecordStatus.PROCESSING)
            .all()
        )
        for record in stuck:
            record.status = models.RecordStatus.PENDING
        if stuck:
            db.commit()

        # Re-queue jobs whose background dispatch was lost or interrupted.
        jobs_to_retry = (
            db.query(models.GenerationJob)
            .filter(
                models.GenerationJob.status.in_(
                    (models.JobStatus.PENDING, models.JobStatus.PROCESSING)
                )
            )
            .all()
        )
        for job in jobs_to_retry:
            job.status = models.JobStatus.PENDING
        if jobs_to_retry:
            db.commit()

        # Re-dispatch (import here to avoid circular at module level)
        from app.worker.processor import process_job
        import threading
        for job in jobs_to_retry:
            threading.Thread(target=process_job, args=(job.id,), daemon=True).start()
    finally:
        db.close()

    yield  # app is running


app = FastAPI(title="Bulk Certificate Generator", lifespan=lifespan)

app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["Jobs"])
app.include_router(verify.router, prefix="/verify", tags=["Verification"])


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok"}
