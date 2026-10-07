"""
test_renderer.py — tests for the certificate rendering function.

These tests call generate_certificate directly, so they are not integration tests.
They use tmp_path so no files escape to the real media directory.
"""
import os
import pytest
from app.rendering.renderer import generate_certificate


@pytest.fixture(autouse=True)
def patch_media(tmp_path, monkeypatch):
    monkeypatch.setattr("app.rendering.renderer.settings.MEDIA_ROOT", tmp_path)
    monkeypatch.setattr("app.rendering.renderer.settings.BASE_URL", "http://testserver")


def test_certificate_file_exists(tmp_path):
    path = generate_certificate("Alice", "Hackathon 2026", "2026-10-07", "CERT-2026-ABCDEF")
    assert os.path.exists(path)


def test_certificate_starts_with_pdf_magic(tmp_path):
    path = generate_certificate("Alice", "Hackathon 2026", "2026-10-07", "CERT-2026-ABCDEF")
    with open(path, "rb") as f:
        header = f.read(4)
    assert header == b"%PDF", f"Expected PDF header, got {header!r}"


def test_certificate_non_trivial_size(tmp_path):
    path = generate_certificate("Alice", "Hackathon 2026", "2026-10-07", "CERT-2026-ABCDEF")
    size = os.path.getsize(path)
    assert size > 5000, f"File seems too small: {size} bytes"


def test_long_name_shrinks_and_does_not_crash(tmp_path):
    long_name = "A" * 100  # max allowed by API
    path = generate_certificate(long_name, "Event", "2026-10-07", "CERT-2026-ABCDEF")
    assert os.path.exists(path)


def test_unicode_devanagari_name_does_not_crash(tmp_path):
    """Devanagari script should pick NotoSansDevanagari and render without error."""
    path = generate_certificate("अर्जुन शर्मा", "Event", "2026-10-07", "CERT-2026-ABCDEF")
    assert os.path.exists(path)


def test_unsupported_character_raises_error(tmp_path):
    from app.rendering.renderer import UnsupportedCharactersError
    # Chinese character, should fail because we only bundled Latin and Devanagari
    with pytest.raises(UnsupportedCharactersError):
        generate_certificate("汉", "Event", "2026-10-07", "CERT-2026-ABCDEF")
