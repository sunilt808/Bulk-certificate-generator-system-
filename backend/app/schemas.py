from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from datetime import datetime
from uuid import UUID

# Recipient schema is intentionally lenient (raw strings) so Pydantic never
# rejects the whole body for one bad row. Per-row validation happens in the
# endpoint with explicit error_code assignment.
class RecipientCreate(BaseModel):
    name: str = ""
    email: str = ""

class JobCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    event_name: Optional[str] = None
    issue_date: Optional[str] = None
    # Envelope-level validation: empty list and over-limit still 422
    recipients: List[RecipientCreate] = Field(..., min_length=1, max_length=1000)

class RecordResponse(BaseModel):
    row_index: int
    name: str
    email: str
    certificate_code: str
    status: str
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class JobResponse(BaseModel):
    id: UUID
    title: str
    status: str
    total: int
    accepted: int = 0
    rejected: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class JobStatusResponse(BaseModel):
    id: UUID
    title: str
    status: str
    total: int
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    pending: int = 0
    percent_complete: float = 0.0
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
