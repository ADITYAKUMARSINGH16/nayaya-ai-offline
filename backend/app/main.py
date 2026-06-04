"""Nyaya AI backend — FastAPI app entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import (
    admin, assistant, cases,    conversations,
    evaluation,
    evidence,
    fir,
    health,
    internal,
    judgments,
    lawyer,
    judge,
    police,
)

app = FastAPI(
    title="Nyaya AI",
    description="Legal reasoning and workflow API",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API = "/api"
app.include_router(health.router,     prefix=API)
app.include_router(assistant.router,  prefix=API)
app.include_router(fir.router,        prefix=API)
app.include_router(cases.router, prefix="/api")
app.include_router(judgments.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(evaluation.router, prefix="/api")
app.include_router(lawyer.router, prefix="/api")
app.include_router(judge.router, prefix="/api")
app.include_router(police.router,     prefix=API)
app.include_router(evidence.router,      prefix=API)

# n8n callback (shared-secret auth, separate from user-facing API surface)
app.include_router(internal.internal_router,    prefix=API)
# FIR status polling endpoint (mounted alongside /api/fir/* for path consistency)
app.include_router(internal.fir_status_router,  prefix=API)


@app.get("/")
async def root():
    return {"service": "nyaya-ai", "docs": "/docs", "health": "/api/health"}
