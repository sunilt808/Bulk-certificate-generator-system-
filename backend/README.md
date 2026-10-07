# Bulk Certificate Generator

A FastAPI backend that accepts a list of recipients, generates PDF certificates
with embedded QR codes, and tracks per-record success and failure.

---

## Tech stack

| Layer | Choice |
|---|---|
| API | FastAPI 0.111+ |
| Database | SQLite via SQLAlchemy 2.0 |
| Background work | FastAPI `BackgroundTasks` (in-process thread) |
| PDF rendering | Pillow + qrcode |
| Validation | Pydantic v2 + email-validator |
| Tests | pytest + TestClient (httpx) |

---

## Setup

```bash
cd backend
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/macOS
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

## Run

```bash
uvicorn app.main:app --reload
# Docs available at http://localhost:8000/docs
```

## Run tests

```bash
pytest -v
```

---

## API Examples

### Submit a job (one valid, one invalid recipient)

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: my-unique-key-001" \
  -d '{
    "title": "Hackathon 2026",
    "event_name": "Shadowfox Hackathon",
    "issue_date": "2026-10-07",
    "recipients": [
      {"name": "Alice Kumar", "email": "alice@example.com"},
      {"name": "", "email": "not-an-email"}
    ]
  }'
```

**Response (202):**
```json
{
  "id": "3f7b2c1a-...",
  "title": "Hackathon 2026",
  "status": "PENDING",
  "total": 2,
  "accepted": 1,
  "rejected": 1,
  "created_at": "2026-10-07T07:00:00Z"
}
```
Headers: `Location: /api/v1/jobs/3f7b2c1a-...`

---

### Poll job status

```bash
curl http://localhost:8000/api/v1/jobs/3f7b2c1a-...
```

**Response:**
```json
{
  "id": "3f7b2c1a-...",
  "status": "COMPLETED_WITH_ERRORS",
  "total": 2,
  "processed": 2,
  "succeeded": 1,
  "failed": 1,
  "pending": 0,
  "percent_complete": 100.0,
  "started_at": "2026-10-07T07:00:01Z",
  "finished_at": "2026-10-07T07:00:03Z",
  "created_at": "2026-10-07T07:00:00Z"
}
```

---

### List recipients (filter by status)

```bash
curl "http://localhost:8000/api/v1/jobs/3f7b2c1a-.../recipients?status=FAILED&limit=50"
```

**Response:**
```json
[
  {
    "row_index": 1,
    "name": "",
    "email": "not-an-email",
    "certificate_code": "CERT-2026-AB1234",
    "status": "FAILED",
    "error_code": "INVALID_NAME",
    "error_message": "Name must not be blank"
  }
]
```

---

### Download one certificate

```bash
curl -OJ http://localhost:8000/api/v1/jobs/certificates/CERT-2026-AB1234/download
```

Returns `application/pdf`.  
`404` if the code is unknown.  
`409` if the certificate exists but is not yet rendered.

---

### Download all (ZIP)

```bash
curl -OJ http://localhost:8000/api/v1/jobs/3f7b2c1a-.../download-all
```

Returns a `application/zip` with one PDF per successful recipient.  
`404` if the job doesn't exist.  
`409` if no certificates have succeeded yet — poll status and retry.

---

### Verify a certificate

```
GET http://localhost:8000/verify/CERT-2026-AB1234
```

Returns an HTML page confirming the certificate is valid (also linked via QR code on the PDF).

---

### Retry render failures

```bash
curl -X POST http://localhost:8000/api/v1/jobs/3f7b2c1a-.../retry
```

Resets only records with `error_code=RENDER_ERROR` back to `PENDING` and re-runs
the processor. Validation failures (`INVALID_EMAIL`, `INVALID_NAME`) are never
retried — the data is still wrong.

---

## Design decisions

### Why FastAPI BackgroundTasks, not Celery?

`BackgroundTasks` runs in the same process as the web server (in a threadpool).
This means:
- Zero operational overhead — no Redis, no worker process, no broker
- Easy to test: call `process_job(id)` directly in tests
- Trivial to debug: one log stream, one process

**Documented upgrade path:** when you need > 1 worker node or want task retries
with exponential backoff, swap `background_tasks.add_task(process_job, id)` for
`celery_app.send_task("process_job", args=[id])`. The `process_job` function
signature doesn't change.

### Two-layer validation

| Layer | Scope | Response |
|---|---|---|
| Pydantic `JobCreate` | Envelope (empty list, over 1000, missing title) | HTTP 422 |
| `_validate_recipient()` | Per-row (blank name, bad email, name > 100 chars) | Record stored as FAILED with `error_code` |

This means one bad email in a 500-recipient batch never blocks the other 499.

### Derived counters, not stored counters

`GET /api/v1/jobs/{id}` runs `GROUP BY status` on `certificate_records`. There
are no `succeeded_count` columns on `generation_jobs`. This avoids:
- Concurrency bugs (two threads both reading 0, both writing 1)
- Stale cached numbers after a retry or recovery

### UUID filenames

Every PDF is saved as `{uuid4().hex}.pdf`. User-submitted names are never used
in filenames. This prevents:
- Path traversal attacks (`../../etc/passwd`)
- Filename collisions across jobs
- Encoding issues with non-ASCII names

### Per-record commit

Each record commits immediately after render, instead of committing the whole
batch at the end. If the process crashes mid-batch:
- Already-succeeded records stay `SUCCESS`
- Startup recovery only re-runs `PENDING` records (idempotent)
- No silent data loss

### Atomic file writes

`generate_certificate` writes to a sibling temp file via `tempfile.mkstemp`,
then calls `os.replace`. `os.replace` is atomic on POSIX and best-effort on
Windows. A partial write never replaces a good file.

### Partial-failure isolation

Each record's render attempt is wrapped in its own `try/except`. Exceptions are
caught, written to `error_message` and `error_code=RENDER_ERROR`, and processing
continues with the next record. The job ends `COMPLETED_WITH_ERRORS` if any
record failed, `COMPLETED` if all succeeded.

---

## Known limitations

- **In-process background work**: a long batch blocks the worker thread and can
  delay HTTP responses. Under heavy load, spin up multiple Uvicorn workers
  (`uvicorn app.main:app --workers 4`), but note SQLite has write contention.
- **SQLite write concurrency**: WAL mode helps readers, but SQLite still allows
  only one writer at a time. With multiple Uvicorn workers, per-record commits
  can queue up.
- **Local disk storage**: files are stored on the server's disk. They're lost if
  the server is replaced or scaled out horizontally.

---

## How I would scale it

| Bottleneck | Solution |
|---|---|
| Background processing | Replace `BackgroundTasks` with Celery + Redis. `process_job` becomes a `@celery_app.task`. |
| Database write concurrency | Move to PostgreSQL. Use `FOR UPDATE SKIP LOCKED` to let multiple workers claim records without stepping on each other. |
| File storage | Upload PDFs to S3 (or GCS). Store the object key in `file_path` instead of a local path. |
| Large batches | Chunk the insert loop into 100-row `INSERT`s. Use `bulk_insert_mappings` for speed. |
| Observability | Add structured logging (structlog), Prometheus metrics on job/record status transitions. |
