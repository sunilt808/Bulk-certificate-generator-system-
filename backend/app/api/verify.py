from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app import models
from app.db import get_db

router = APIRouter()

@router.get("/{certificate_code}", response_class=HTMLResponse)
def verify_certificate(certificate_code: str, request: Request, db: Session = Depends(get_db)):
    record = db.query(models.CertificateRecord).filter(models.CertificateRecord.certificate_code == certificate_code).first()
    if not record or record.status != models.RecordStatus.SUCCESS:
        raise HTTPException(status_code=404, detail="Invalid or unverified certificate code")
    
    # In a real app, you would use a Jinja2 template here.
    html_content = f"""
    <html>
        <head>
            <title>Certificate Verification</title>
            <style>
                body {{ font-family: sans-serif; text-align: center; padding: 50px; background-color: #f4f4f9; }}
                .card {{ background: white; padding: 40px; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); display: inline-block; }}
                .valid {{ color: #2ecc71; font-weight: bold; font-size: 24px; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h1>Certificate Verified</h1>
                <p class="valid">✓ VALID CERTIFICATE</p>
                <p><strong>Code:</strong> {record.certificate_code}</p>
                <p><strong>Awarded to:</strong> {record.name}</p>
                <p><strong>Date of Completion:</strong> {record.completed_at.strftime("%B %d, %Y") if record.completed_at else "N/A"}</p>
            </div>
        </body>
    </html>
    """
    return html_content
