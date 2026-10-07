# Bulk Certificate Generator

FastAPI backend for generating bulk PDF certificates with QR verification,
per-recipient validation, background processing, and SQLite persistence.

## Project documentation

The application lives in [`backend/`](./backend/).

- Setup, API examples, design decisions, limitations, and scaling notes:
  [`backend/README.md`](./backend/README.md)
- Run tests from the backend directory:

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
pytest -v
```

## Run the API

```powershell
cd backend
uvicorn app.main:app --reload
```

Then open <http://localhost:8000/docs>.

The repository includes the certificate template and Latin/Devanagari fonts
under `backend/app/rendering/`.
