import pytest
from app import models
import time

def test_create_job(client):
    payload = {
        "title": "Test Job",
        "recipients": [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "bob@example.com"}
        ]
    }
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 202
    data = response.json()
    assert data["title"] == "Test Job"
    assert data["total"] == 2
    assert "id" in data

def test_input_validation(client):
    # Missing required name
    payload = {
        "title": "Invalid Job",
        "recipients": [
            {"email": "invalid@example.com"}
        ]
    }
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 422
    
    # Invalid email
    payload2 = {
        "title": "Invalid Email",
        "recipients": [
            {"name": "John", "email": "not-an-email"}
        ]
    }
    response2 = client.post("/api/v1/jobs", json=payload2)
    assert response2.status_code == 422

def test_job_status_and_processing(client):
    # Setup job
    payload = {
        "title": "Process Test",
        "recipients": [
            {"name": "Test User", "email": "test@example.com"}
        ]
    }
    response = client.post("/api/v1/jobs", json=payload)
    job_id = response.json()["id"]
    
    # Poll until done
    max_retries = 10
    done = False
    for _ in range(max_retries):
        resp = client.get(f"/api/v1/jobs/{job_id}")
        data = resp.json()
        if data["status"] in ["COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"]:
            done = True
            break
        time.sleep(0.5)
        
    if data["succeeded_count"] != 1:
        rec_resp = client.get(f"/api/v1/jobs/{job_id}/recipients")
        print("ERRORS:", [r["error_message"] for r in rec_resp.json()])
    assert data["succeeded_count"] == 1, f"Data: {data}"
    assert data["failed_count"] == 0
    assert data["progress_percentage"] == 100.0

def test_partial_failure(client, monkeypatch):
    # Force the renderer to fail for specific names
    from app.rendering import renderer
    original_generate = renderer.generate_certificate
    
    def mock_generate(name, event_name, issue_date, certificate_code):
        if name == "Fail Name":
            raise ValueError("Intentional generation failure")
        return original_generate(name, event_name, issue_date, certificate_code)
        
    monkeypatch.setattr("app.worker.processor.generate_certificate", mock_generate)
    
    payload = {
        "title": "Partial Fail Test",
        "recipients": [
            {"name": "Good Name", "email": "good@example.com"},
            {"name": "Fail Name", "email": "fail@example.com"}
        ]
    }
    
    response = client.post("/api/v1/jobs", json=payload)
    job_id = response.json()["id"]
    
    # Wait for completion
    done = False
    for _ in range(10):
        resp = client.get(f"/api/v1/jobs/{job_id}")
        data = resp.json()
        if data["status"] in ["COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"]:
            done = True
            break
        time.sleep(0.5)
        
    assert done
    assert data["status"] == "COMPLETED_WITH_ERRORS"
    assert data["succeeded_count"] == 1, f"Data: {data}"
    assert data["failed_count"] == 1
    
    # Verify records
    rec_resp = client.get(f"/api/v1/jobs/{job_id}/recipients")
    records = rec_resp.json()
    assert len(records) == 2
    for r in records:
        if r["name"] == "Fail Name":
            assert r["status"] == "FAILED"
            assert "Intentional generation failure" in r["error_message"]
        else:
            assert r["status"] == "SUCCESS"
