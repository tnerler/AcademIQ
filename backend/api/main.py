"""
AcademIQ REST API.

Calistirma:
  uv run uvicorn backend.api.main:app --reload
Dokumantasyon (UI kontrati): http://localhost:8000/docs
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import routes_cagrilar, routes_cvs, routes_match
from backend.cagrilar.db import init_schema
from backend.config import get_settings
from backend.matching.search import get_bm25


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_schema()  # cagri tablolari (idempotent)
    get_bm25()  # BM25 indeksini ilk istekten once bellege yukle
    yield


app = FastAPI(title="AcademIQ API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(routes_cvs.router)
app.include_router(routes_match.router)
app.include_router(routes_cagrilar.router)


@app.get("/health", tags=["Sistem"])
def health() -> dict:
    return {"status": "ok"}
