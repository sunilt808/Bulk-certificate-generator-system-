# Bulk Certificate Generator

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)
![Tests](https://img.shields.io/badge/tests-34%20passing-success)

A FastAPI service that accepts a batch of recipients and generates
personalized PDF certificates with QR-code verification links.

The project is designed as a small, understandable backend: SQLite and
FastAPI `BackgroundTasks` keep local development simple, while the application
boundaries document the path to Celery, PostgreSQL, and object storage when the
workload grows.

## Features

- Bulk job creation with a 202 Accepted response
- Per-recipient validation and partial-failure isolation
- Idempotent submissions with `Idempotency-Key`
- Background PDF generation with per-record progress tracking
- Bundled Noto Sans and Devanagari fonts
- QR codes linking to a public certificate verification endpoint
- Atomic PDF writes using temporary files and `os.replace`
- Safe UUID-based filenames that never contain user input
- Retry endpoint for failed render records
- Startup recovery for persisted `PENDING` and interrupted `PROCESSING` jobs
- SQLite WAL mode for better reader concurrency
- Bounded worker batches for large jobs
- API, rendering, recovery, retry, and retrieval tests

## Technology

| Area | Technology |
| --- | --- |
| API | FastAPI |
| ORM | SQLAlchemy 2 |
| Database | SQLite with WAL mode |
| Rendering | Pillow |
| QR codes | `qrcode` |
| Validation | Pydantic and `email-validator` |
| Background work | FastAPI `BackgroundTasks` |
| Testing | pytest and FastAPI `TestClient` |

## Quick start

### Windows PowerShell

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
pytest -v
uvicorn app.main:app --reload
```

### Linux/macOS

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
pytest -v
uvicorn app.main:app --reload
```

The API will be available at:

- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>
- Health check: <http://localhost:8000/health>

Expected health response:

```json
{"status": "ok"}
```

No font download is required. The certificate template and Latin/Devanagari
fonts are bundled under `backend/app/rendering/`.

## Configuration

Copy `.env.example` to `.env` in `backend/`:

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./certificates.db` | SQLAlchemy database URL |
| `MEDIA_ROOT` | `./media` | Directory for generated PDFs |
| `MAX_RECIPIENTS_PER_JOB` | `1000` | Maximum recipients in one request |
| `BASE_URL` | `http://localhost:8000` | Base URL embedded in QR links |

Generated databases, media, PDFs, virtual environments, and `.env` files are
ignored by Git.

## API workflow

### 1. Create a job

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: hackathon-2026-001" \
  -d '{
    "title": "Hackathon 2026",
    "event_name": "Shadowfox Hackathon",
    "issue_date": "2026-10-07",
    "recipients": [
      {"name": "Alice Kumar", "email": "alice@example.com"},
      {"name": "अर्जुन शर्मा", "email": "arjun@example.com"}
    ]
  }'
```

The endpoint returns `202 Accepted` and a `Location` header. Valid recipients
are stored as `PENDING`; invalid recipients are recorded as `FAILED` without
blocking valid rows.

### 2. Poll job status

```bash
curl http://localhost:8000/api/v1/jobs/{job_id}
```

The response reports total, processed, succeeded, failed, pending, and
percentage-complete counts.

### 3. Download certificates

```bash
# One certificate
curl -OJ http://localhost:8000/api/v1/jobs/certificates/{certificate_code}/download

# All successful certificates as a ZIP
curl -OJ http://localhost:8000/api/v1/jobs/{job_id}/download-all
```

### 4. Verify a certificate

```text
GET http://localhost:8000/verify/{certificate_code}
```

The same verification URL is encoded in the certificate QR code.

### 5. Retry failed renders

```bash
curl -X POST http://localhost:8000/api/v1/jobs/{job_id}/retry
```

Only render failures are retried. Input-validation failures are not retried
because the submitted data is still invalid. There is no automatic retry
system; the client explicitly calls this endpoint by design.

## Request lifecycle

1. `POST /api/v1/jobs` validates the request envelope and each recipient.
2. The job and all recipient records are committed to SQLite.
3. FastAPI schedules `process_job` in the current process.
4. The worker opens its own SQLAlchemy session, because the request session is
   closed after the HTTP response.
5. Each `PENDING` record is rendered and committed independently.
6. The client polls the job endpoint until records reach `SUCCESS` or `FAILED`.
7. Startup recovery requeues persisted `PENDING` and interrupted `PROCESSING`
   jobs.

## Reliability and design choices

- **Per-recipient validation:** one invalid row does not reject an entire
  batch.
- **Per-record commits:** completed records survive a crash midway through a
  large job.
- **Atomic file writes:** a temporary PDF is replaced into its final path only
  after a successful render.
- **Derived counters:** job counts are calculated from record statuses rather
  than maintained as race-prone cached counters.
- **Safe filenames:** generated filenames use UUIDs, not recipient names.
- **Idempotency:** repeated requests with the same idempotency key return the
  existing job instead of creating a duplicate.

## Known limitations

- `BackgroundTasks` is in-process and in-memory. It is appropriate for a
  small deployment, but it is not a durable distributed queue.
- WAL and short commits keep SQLite contention low, but multiple worker
  processes or large simultaneous jobs require PostgreSQL.
- Worker records are claimed atomically with a conditional update. The
  configurable batch size keeps memory bounded for large jobs.
- Devanagari conjunct shaping depends on optional Pillow Raqm support. The
  fonts are bundled, but complex conjuncts are not guaranteed to shape
  correctly when Raqm is unavailable.
- PDFs are stored on local disk. Horizontal deployments should use S3,
  Google Cloud Storage, or another shared object store.

## Testing

Run the full backend suite from `backend/`:

```bash
pytest -v
```

The suite covers job creation, validation, idempotency, partial failures,
rendering, retry behavior, startup recovery, downloads, ZIP output, and
certificate retrieval.

## Project structure

```text
.
├── README.md
├── backend/
│   ├── app/
│   │   ├── api/              # Job and verification endpoints
│   │   ├── rendering/       # Pillow renderer, template, and bundled fonts
│   │   ├── worker/          # Background job processor
│   │   ├── config.py        # Environment-backed settings
│   │   ├── db.py            # SQLAlchemy engine and sessions
│   │   ├── models.py        # Database models and statuses
│   │   └── schemas.py       # Pydantic request/response models
│   ├── tests/               # Automated test suite
│   ├── .env.example
│   ├── README.md            # Detailed backend notes
│   └── requirements.txt
```

## Scaling path

| Current constraint | Production direction |
| --- | --- |
| In-process background tasks | Celery or another durable worker queue |
| SQLite single-writer behavior | PostgreSQL with atomic row claiming |
| Local PDF files | S3/GCS-compatible object storage |
| Large in-memory record batches | Paginated/chunked processing |
| Limited operational visibility | Structured logs, metrics, and tracing |

See [`backend/README.md`](./backend/README.md) for detailed API examples and
implementation notes.
