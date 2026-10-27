"""FastAPI application entry point.

Run from the repository root:

    pip install -r backend/requirements.txt
    cp .env.example .env
    uvicorn backend.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pymongo.asynchronous.mongo_client import AsyncMongoClient

from .auth.router import router as auth_router
from .config import get_settings
from .database import create_indexes
from .questions.library_router import router as libraries_router
from .questions.router import router as questions_router
from .stats.router import router as stats_router
from .surveys.public_router import router as public_surveys_router
from .surveys.router import router as surveys_router
from .web import router as web_router

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    client = AsyncMongoClient(settings.mongodb_uri, tz_aware=True)
    db = client[settings.mongodb_db]
    app.state.mongo_client = client
    app.state.db = db
    if settings.auto_create_indexes:
        await create_indexes(db)
    try:
        yield
    finally:
        await client.close()


app = FastAPI(
    title="Survey System API",
    version="1.0.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(auth_router)
app.include_router(stats_router)
app.include_router(questions_router)
app.include_router(libraries_router)
app.include_router(surveys_router)
app.include_router(public_surveys_router)
app.include_router(web_router)


__all__ = ["app"]
