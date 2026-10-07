import os
import uuid
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw
import qrcode

from app.config import settings


def _ensure_media_dir() -> Path:
    settings.MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
    return settings.MEDIA_ROOT


def _get_template() -> Path:
    """Create a blank white A4 landscape template once and cache it."""
    media = _ensure_media_dir()
    template_path = media / "template.png"
    if not template_path.exists():
        img = Image.new("RGB", (1123, 794), color=(255, 255, 255))  # A4 landscape @ 96 DPI
        d = ImageDraw.Draw(img)
        d.text((100, 100), "Certificate of Completion", fill=(0, 0, 0))
        img.save(template_path)
    return template_path


def generate_certificate(name: str, event_name: str, issue_date: str, certificate_code: str) -> str:
    """
    Render a certificate image and save it as PDF.

    Returns the absolute path to the saved PDF.
    Files are written atomically (write to temp → os.replace) so a crash
    mid-write never leaves a corrupt file at the final path.
    """
    media = _ensure_media_dir()

    img = Image.open(_get_template())
    d = ImageDraw.Draw(img)

    d.text((100, 300), f"Awarded to: {name}", fill=(0, 0, 0))
    if event_name:
        d.text((100, 400), f"For: {event_name}", fill=(0, 0, 0))
    if issue_date:
        d.text((100, 500), f"Date: {issue_date}", fill=(0, 0, 0))

    # QR code links to the public verification endpoint
    verify_url = f"{settings.BASE_URL}/verify/{certificate_code}"
    qr = qrcode.QRCode(box_size=4, border=2)
    qr.add_data(verify_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_w, qr_h = qr_img.size
    img.paste(qr_img, (img.width - qr_w - 50, img.height - qr_h - 50))

    # UUID filename — never derived from user input
    final_path = media / f"{uuid.uuid4().hex}.pdf"

    # Atomic write: save to a sibling temp file, then replace
    fd, tmp_path = tempfile.mkstemp(dir=media, suffix=".pdf")
    os.close(fd)
    try:
        img.save(tmp_path, "PDF", resolution=100.0)
        os.replace(tmp_path, final_path)
    except Exception:
        # Clean up temp file if save failed
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return str(final_path)
