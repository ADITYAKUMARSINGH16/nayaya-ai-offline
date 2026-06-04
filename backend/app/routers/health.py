from fastapi import APIRouter

from app.config import settings
from app.services.legal_graph import graph_stats

router = APIRouter(tags=["health"])


def _active_model() -> str:
    """Return the model name actually in use for the configured provider."""
    p = settings.llm_provider.lower()
    if p == "groq":
        return settings.groq_model
    if p == "openai":
        return settings.openai_model
    if p == "ollama":
        return settings.ollama_model
    return "unknown"


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "env": settings.app_env,
        "version": "2.0.0",
        "llm_provider": settings.llm_provider,
        "llm_model": _active_model(),
        "embeddings_provider": settings.embeddings_provider,
        "embeddings_model": settings.embeddings_model,
        "vector_index": settings.qdrant_collection,
        "auth_required": settings.auth_required,
        "graph": graph_stats(),
    }
