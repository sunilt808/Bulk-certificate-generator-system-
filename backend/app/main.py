from fastapi import FastAPI
from app.db import engine, Base
from app.api import jobs
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables
    Base.metadata.create_all(bind=engine)
    
    # Startup recovery and runner thread would be initialized here
    yield
    # Shutdown runner thread

app = FastAPI(title="Bulk Certificate Generator", lifespan=lifespan)

app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["Jobs"])

@app.get("/health")
def health_check():
    return {"status": "ok"}
