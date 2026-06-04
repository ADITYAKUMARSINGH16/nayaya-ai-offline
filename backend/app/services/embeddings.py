"""Provider-agnostic text embeddings for RAG.

Defaults to Ollama `nomic-embed-text` (768-dim) to match the existing Pinecone
index `rag-legal`. Switch via EMBEDDINGS_PROVIDER.
"""
from __future__ import annotations

import httpx

from app.config import settings


async def embed_text(text: str) -> list[float]:
    vectors = await embed_texts([text])
    return vectors[0]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    provider = settings.embeddings_provider.lower()
    if provider == "ollama":
        return await _ollama_embed(texts)
    if provider == "openai":
        return await _openai_embed(texts)
    if provider == "sentence_transformers":
        return _st_embed(texts)
    raise RuntimeError(f"Unknown EMBEDDINGS_PROVIDER: {settings.embeddings_provider}")


async def _ollama_embed(texts: list[str]) -> list[list[float]]:
    base = settings.ollama_base_url.rstrip("/")
    out: list[list[float]] = []
    async with httpx.AsyncClient(timeout=600.0) as client:
        for t in texts:
            resp = await client.post(
                f"{base}/api/embeddings",
                json={"model": settings.embeddings_model, "prompt": t},
            )
            resp.raise_for_status()
            out.append(resp.json()["embedding"])
    return out


_OPENAI_BATCH = 512   # well under OpenAI's 2048-input cap, leaves room for token-count


async def _openai_embed(texts: list[str]) -> list[list[float]]:
    """OpenAI embeddings with dimension reduction and request batching.

    text-embedding-3-small/large support `dimensions` (256/512/768/1024/1536/3072)
    via Matryoshka — we request `settings.embeddings_dim` so vectors match the
    existing Pinecone index without recreating it.

    OpenAI's embeddings endpoint caps inputs per request at 2048 and total
    tokens at ~300k. We chunk into _OPENAI_BATCH-sized slices so big ingests
    (e.g. 6k+ vectors from multi-vector enrichment) don't hit either limit.
    """
    model = settings.embeddings_model
    is_v3 = model.lower().startswith("text-embedding-3")
    out: list[list[float]] = []
    async with httpx.AsyncClient(timeout=120.0) as client:
        for i in range(0, len(texts), _OPENAI_BATCH):
            slice_ = texts[i : i + _OPENAI_BATCH]
            body: dict = {"model": model, "input": slice_}
            if is_v3:
                body["dimensions"] = settings.embeddings_dim
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json=body,
            )
            if resp.status_code >= 400:
                # Surface OpenAI's actual error message — much more useful than a generic 400.
                raise RuntimeError(
                    f"OpenAI embeddings {resp.status_code}: {resp.text[:500]}"
                )
            data = resp.json()["data"]
            out.extend(item["embedding"] for item in data)
    return out


_st_model = None


def _st_embed(texts: list[str]) -> list[list[float]]:
    global _st_model
    if _st_model is None:
        from sentence_transformers import SentenceTransformer  # lazy, heavy

        _st_model = SentenceTransformer(settings.embeddings_model, trust_remote_code=True)
    return _st_model.encode(texts).tolist()
