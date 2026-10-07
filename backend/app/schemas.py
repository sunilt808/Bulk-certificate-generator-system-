from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import List, Optional
from datetime import datetime
from uuid import UUID

class RecipientCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr

class JobCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    event_name: Optional[str] = None
    issue_date: Optional[str] = None
    recipients: List[RecipientCreate] = Field(..., min_length=1, max_length=1000)

class RecordResponse(BaseModel):
    id: UUID
    row_index: int
    name: str
    email: str
    certificate_code: str
    status: str
    error_message: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

class JobResponse(BaseModel):
    id: UUID
    title: str
    status: str
    total: int
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class JobStatusResponse(JobResponse):
    succeeded_count: int = 0
    failed_count: int = 0
    pending_count: int = 0
    processing_count: int = 0
    progress_percentage: float = 0.0
