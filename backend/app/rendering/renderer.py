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


class UnsupportedCharactersError(Exception):
    pass


def _has_unsupported_chars(font, text: str) -> bool:
    """Check if any character is missing by comparing against the .notdef box."""
    missing_length = font.getlength('\uFFFF')
    missing_bbox = font.getmask('\uFFFF').getbbox()
    for char in text:
        if char in (' ', '\n', '\t'):
            continue
        if font.getlength(char) == missing_length and font.getmask(char).getbbox() == missing_bbox:
            return True
    return False


def generate_certificate(name: str, event_name: str, issue_date: str, certificate_code: str) -> str:
    """
    Render a certificate image and save it as PDF.

    Returns the absolute path to the saved PDF.
    Files are written atomically (write to temp → os.replace) so a crash
    mid-write never leaves a corrupt file at the final path.
    """
    from PIL import ImageFont
    
    media = _ensure_media_dir()

    img = Image.open(_get_template())
    d = ImageDraw.Draw(img)

    # Pick font based on Devanagari script presence
    is_devanagari = any(0x0900 <= ord(c) <= 0x097F for c in name)
    font_file = "NotoSansDevanagari-Regular.ttf" if is_devanagari else "NotoSans-Regular.ttf"
    font_path = Path(__file__).parent / "fonts" / font_file

    # Auto-shrink font
    font_size = 60
    max_width = 800
    font = ImageFont.truetype(str(font_path), font_size)
    while font.getlength(name) > max_width and font_size > 10:
        font_size -= 2
        font = ImageFont.truetype(str(font_path), font_size)

    # Check for unsupported characters
    if _has_unsupported_chars(font, name):
        raise UnsupportedCharactersError(f"Name contains unsupported characters for font {font_file}")

    d.text((100, 300), f"Awarded to: {name}", fill=(0, 0, 0), font=font)
    
    # Fallback to default PIL font for these just to keep it simple, 
    # but let's load a smaller NotoSans for them if we want to be safe, 
    # or just use default.
    default_font = ImageFont.load_default()
    if event_name:
        d.text((100, 400), f"For: {event_name}", fill=(0, 0, 0), font=default_font)
    if issue_date:
        d.text((100, 500), f"Date: {issue_date}", fill=(0, 0, 0), font=default_font)

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
