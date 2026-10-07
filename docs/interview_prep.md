# Stage 2: Interview Cheat Sheet

## 1. Request Flow (POST /api/v1/jobs)
1. **API Router** (`app/api/jobs.py` -> `create_job`): 
   - Checks `Idempotency-Key`.
   - Creates `GenerationJob` envelope (SQLAlchemy `db.add`).
   - Iterates recipients, calls `_validate_recipient()` (raw string validation, no Pydantic).
   - Valid rows: `CertificateRecord` as `PENDING`. Invalid rows: `CertificateRecord` as `FAILED`.
   - Calls `background_tasks.add_task(process_job, db_job.id)`.
   - Returns 202 Accepted with `Location` header. `Response(content=...,
     status_code=202)` serializes the `JobResponse`, sets the header, and
     explicitly returns the asynchronous-acceptance status.
2. **Background Processor** (`app/worker/processor.py` -> `process_job`):
   - Flips job to `PROCESSING`, creates a new `SessionLocal`.
   - Fetches only `PENDING` records (idempotent loop). It opens its own
     `SessionLocal` because the request session is closed after the response.
   - Iterates each record, calls `generate_certificate()`.
   - Updates record to `SUCCESS` and commits immediately per record.
   - Updates job status (`COMPLETED` or `COMPLETED_WITH_ERRORS`).
3. **Renderer** (`app/rendering/renderer.py` -> `generate_certificate`):
   - Opens template, picks script (NotoSans or Devanagari), auto-shrinks font.
   - Throws `UnsupportedCharactersError` if glyph missing.
   - Saves PDF atomically (tempfile + `os.replace`).

## 2. Eight Design Decisions (with justifications)
1. **BackgroundTasks vs Celery**: Zero operational overhead (no Redis/broker required), fits inside Uvicorn process, easy to deploy for an MVP.
2. **Per-recipient validation**: 1 bad email in 500 shouldn't block the other 499 from getting certificates; saves client from fixing data and resubmitting all.
3. **Derived counters (GROUP BY)**: Prevents race conditions and stale cached numbers. `succeeded`/`failed` counts are always real-time correct.
4. **Per-record commits**: If the server crashes mid-batch, completed records are saved and aren't rolled back, allowing fast recovery. SQLite contention stays low with WAL and short commits, but several worker processes or large jobs at once are the point where PostgreSQL is the scaling path.
5. **Safe UUID filenames**: Prevents path traversal (`../../etc/passwd`), filename collisions, and Unicode encoding issues on disk.
6. **Atomic file writes**: Uses `tempfile.mkstemp` and `os.replace`; prevents partial/corrupt PDFs if process is killed mid-write.
7. **Idempotent processing**: `process_job` only selects `PENDING` records; safely re-runnable after a crash without generating duplicates.
8. **Startup recovery**: A job lost before `process_job` starts is recovered on the next restart because persisted `PENDING` and `PROCESSING` jobs are requeued; a dispatch still in RAM can be lost. Failed renders are recorded and the client calls `POST /retry`. This is a design choice, not automatic retry.
9. **Atomic claim gap**: There is no atomic claim step, so two overlapping `process_job` runs on one job could both pick the same `PENDING` record. Fix this with `UPDATE ... WHERE status='PENDING'` and check the affected row count before rendering.

## 3. Top 5 Riskiest / Weakest Spots
1. **Thread blocking**: `process_job` (`processor.py`) does heavy image I/O synchronously. It blocks one of FastAPI's threadpool threads for the whole batch. 
2. **SQLite Write Contention**: WAL and short per-record commits keep contention low, but several worker processes or large simultaneous jobs can still contend. PostgreSQL is the scaling path.
3. **No automatic retry**: Failed renders are recorded and the client calls `POST /retry`. This is a design choice.
4. **In-process state**: The `BackgroundTasks` queue lives in RAM. If Uvicorn is killed before `process_job` starts, the dispatch can be lost; startup recovery requeues persisted `PENDING` and `PROCESSING` jobs.
5. **Disk capacity**: PDFs are stored locally (`renderer.py`). If you scale horizontally to 3 servers, users hit a 404 if they poll the wrong server. No S3/cloud storage.
