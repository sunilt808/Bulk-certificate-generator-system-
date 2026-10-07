import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
import enum
from app.db import Base

class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    FAILED = "FAILED"

class RecordStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"

def get_utc_now():
    return datetime.now(timezone.utc)

class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String, nullable=False)
    event_name = Column(String, nullable=True)
    issue_date = Column(String, nullable=True)
    status = Column(String, default=JobStatus.PENDING)
    total = Column(Integer, default=0)
    idempotency_key = Column(String, unique=True, nullable=True, index=True)
    
    created_at = Column(DateTime, default=get_utc_now)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    records = relationship("CertificateRecord", back_populates="job", cascade="all, delete-orphan")


class CertificateRecord(Base):
    __tablename__ = "certificate_records"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("generation_jobs.id"), index=True)
    row_index = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    certificate_code = Column(String, unique=True, index=True, default=lambda: f"CERT-{datetime.now(timezone.utc).year}-{uuid.uuid4().hex[:6].upper()}")
    
    status = Column(String, default=RecordStatus.PENDING)
    error_code = Column(String, nullable=True)
    error_message = Column(String, nullable=True)
    file_path = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=get_utc_now)
    completed_at = Column(DateTime, nullable=True)

    job = relationship("GenerationJob", back_populates="records")
