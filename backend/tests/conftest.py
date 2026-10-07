"""
conftest.py — shared fixtures for the test suite.

Key design decisions:
- We use a named temp file for the test DB (not :memory:) so that the lifespan
  `create_all` call and the `TestingSession` both talk to the same SQLite file.
- tmp_path is used for the media directory so renderer files stay isolated.
- SessionLocal in the processor is monkeypatched to use TestingSession so that
  background calls from process_job() see the same rows as the HTTP client.
"""
import os
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db import Base, get_db
import app.db as app_db


@pytest.fixture()
def db(tmp_path):
    """
    Create a fresh SQLite file per test inside tmp_path.
    Yield (session, SessionFactory, engine).
    Teardown drops all tables.
    """
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Patch the module-level engine so lifespan create_all hits the test DB
    original_engine = app_db.engine
    original_session = app_db.SessionLocal
    app_db.engine = engine
    app_db.SessionLocal = TestingSession

    Base.metadata.create_all(bind=engine)
    session = TestingSession()
    try:
        yield session, TestingSession, engine
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
        app_db.engine = original_engine
        app_db.SessionLocal = original_session


@pytest.fixture()
def client(db, monkeypatch, tmp_path):
    """
    HTTP test client wired to the in-file test DB and a temp media directory.
    """
    session, TestingSession, engine = db

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("app.worker.processor.SessionLocal", TestingSession)
    monkeypatch.setattr("app.rendering.renderer.settings.MEDIA_ROOT", tmp_path)
    monkeypatch.setattr("app.rendering.renderer.settings.BASE_URL", "http://testserver")

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    app.dependency_overrides.clear()
