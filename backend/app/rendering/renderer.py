from PIL import Image, ImageDraw, ImageFont
import qrcode
from pathlib import Path
import uuid
import os

from app.config import settings

def ensure_media_dir():
    settings.MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

def create_dummy_template() -> Path:
    ensure_media_dir()
    template_path = settings.MEDIA_ROOT / "template.png"
    if not template_path.exists():
        img = Image.new('RGB', (1123, 794), color=(255, 255, 255)) # A4 Landscape 96 DPI
        d = ImageDraw.Draw(img)
        d.text((100, 100), "Certificate of Completion", fill=(0, 0, 0))
        img.save(template_path)
    return template_path

def generate_certificate(name: str, event_name: str, issue_date: str, certificate_code: str) -> str:
    template_path = create_dummy_template()
    img = Image.open(template_path)
    d = ImageDraw.Draw(img)
    
    # Simple placement for now. Can be enhanced with Noto Sans and QR codes.
    # We use default font since this is just a stub implementation
    d.text((100, 300), f"Awarded to: {name}", fill=(0, 0, 0))
    if event_name:
        d.text((100, 400), f"For: {event_name}", fill=(0, 0, 0))
    if issue_date:
        d.text((100, 500), f"Date: {issue_date}", fill=(0, 0, 0))
        
    # Generate QR Code
    qr = qrcode.QRCode(box_size=4, border=2)
    verify_url = f"http://localhost:8000/verify/{certificate_code}"
    qr.add_data(verify_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    
    # Paste QR Code on the bottom right
    img.paste(qr_img, (img.width - qr_img.width - 50, img.height - qr_img.height - 50))
        
    filename = f"{uuid.uuid4().hex}.pdf"
    filepath = settings.MEDIA_ROOT / filename
    
    img.save(filepath, "PDF", resolution=100.0)
    return str(filepath)
