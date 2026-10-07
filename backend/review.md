# Project Review: Bulk Certificate Generator

## Task Checklist

| Task | Status | Note |
|---|---|---|
| A1: Per-recipient validation | ✅ Done | `_validate_recipient()` in `jobs.py`; invalid rows stored as FAILED records with `error_code` |
| A2: Job status & progress | ✅ Done | `GET /api/v1/jobs/{id}` returns `succeeded`, `failed`, `pending`, `processed`, `percent_complete`, `started_at`, `finished_at` |
| A3: Recipients listing | ✅ Done | Supports `?status=`, `?limit=` (capped 200), `?offset=`, ordered by `row_index` |
| A4: Retrieval correctness | ✅ Done | 404 unknown, 409 not-ready, 200 PDF; ZIP uses `certificate_code` filenames; atomic writes |
| A5: Test gaps | ✅ Done | 33 tests across 5 files; all pass |
| A6: requirements.txt + .env.example | ✅ Done | Minimum versions pinned; `BASE_URL`, `MEDIA_DIR`, `MAX_RECIPIENTS` documented |
| A7: README.md | ✅ Done | curl examples, design decisions, limitations, scaling path |
| B8: Startup recovery | ✅ Done | `lifespan` in `main.py` resets stuck `PROCESSING` records; test in `test_recovery.py` |
| B9: Idempotency-Key header | ✅ Done | `POST /api/v1/jobs` with same key returns existing job without duplicate; tests in `test_idempotency.py` |
| B10: POST /{id}/retry | ✅ Done | Resets only `RENDER_ERROR` records; 409 if still PROCESSING or no render failures; tests in `test_partial_failure.py` |
| B11: Unicode font support | ✅ Done with shaping limitation | Bundled NotoSans and NotoSansDevanagari fonts are loaded by `generate_certificate()`; complex conjunct shaping depends on Pillow's optional Raqm support. |

---

## Final pytest output

```
======================== 33 passed, 1 warning in 4.92s ========================
```

All 33 tests across 5 test files pass. The one warning is a harmless
`StarletteDeprecationWarning` about the `httpx`/`starlette` testclient version.

---

## Interview prep: things to explain

| What | File | Function |
|---|---|---|
| Why `_validate_recipient` is a standalone function | `app/api/jobs.py` | `_validate_recipient()` |
| Why `RecipientCreate` has no Pydantic validators (raw strings) | `app/schemas.py` | `RecipientCreate` |
| Why all-invalid jobs are finalized immediately without dispatching | `app/api/jobs.py` | `create_job()` |
| Why the 202 response uses `Response(content=..., status_code=202)` instead of `return db_job` | `app/api/jobs.py` | `create_job()` — it serializes `JobResponse`, sets `Location`, and explicitly returns the asynchronous-acceptance status |
| Why counts are derived with GROUP BY, not stored columns | `app/api/jobs.py` | `get_job_status()` |
| Why `os.replace()` is used and what "atomic" means here | `app/rendering/renderer.py` | `generate_certificate()` |
| Why we commit per-record, not per-batch | `app/worker/processor.py` | `process_job()` |
| Why `process_job` is idempotent (skips SUCCESS records) | `app/worker/processor.py` | `process_job()` |
| Why `process_job` opens its own session | `app/worker/processor.py` | `process_job()` — the request-scoped session is closed after the response |
| How startup recovery works and its limitation (not truly crash-safe on mid-render) | `app/main.py` | `lifespan()` |
| Why overlapping processors have an atomic-claim gap | `app/worker/processor.py` | `process_job()` — use `UPDATE ... WHERE status='PENDING'` and check affected rows |
| Why `SessionLocal` is monkeypatched in tests instead of using `get_db` override for the processor | `tests/conftest.py` | `client` fixture |
| Why the engine is patched at module level in conftest | `tests/conftest.py` | `db` fixture |
| Why validation failures are NOT retried by `POST /retry` | `app/api/jobs.py` | `retry_failed_certificates()` |
| What `Idempotency-Key` prevents and its DB uniqueness constraint | `app/models.py` | `GenerationJob.idempotency_key` |
| Why filenames inside the ZIP are `certificate_code.pdf`, not user's name | `app/api/jobs.py` | `download_all_certificates()` |
| Why WAL mode is set on SQLite | `app/db.py` | `set_sqlite_pragma()` |

---

## Files and their roles

| File | Role |
|---|---|
| `app/models.py` | SQLAlchemy ORM — `GenerationJob`, `CertificateRecord`, enums |
| `app/schemas.py` | Pydantic I/O shapes — lenient `RecipientCreate`, `JobStatusResponse` |
| `app/config.py` | Pydantic Settings — `DATABASE_URL`, `MEDIA_ROOT`, `BASE_URL`, `MAX_RECIPIENTS_PER_JOB` |
| `app/db.py` | Engine, `SessionLocal`, `get_db` dependency, WAL pragmas |
| `app/main.py` | FastAPI app factory, lifespan (create_all + startup recovery), router mounts |
| `app/api/jobs.py` | All job endpoints + `_validate_recipient` |
| `app/api/verify.py` | Public HTML verification page |
| `app/worker/processor.py` | `process_job()` — idempotent batch renderer |
| `app/rendering/renderer.py` | `generate_certificate()` — Pillow + QR code + atomic write |
| `tests/conftest.py` | Shared fixtures (temp-file DB, patched engine, temp media dir) |
| `tests/test_jobs.py` | Job creation, validation, status, recipients listing |
| `tests/test_partial_failure.py` | Partial failure isolation and retry endpoint |
| `tests/test_retrieval.py` | Download 200/404/409, ZIP contents, path traversal |
| `tests/test_renderer.py` | File existence, PDF header, size, Unicode, long names |
| `tests/test_idempotency.py` | Idempotency-Key deduplication |
| `tests/test_recovery.py` | Startup recovery for stuck PROCESSING records |
