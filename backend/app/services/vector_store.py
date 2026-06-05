"""Swappable vector store access (Qdrant/Pinecone) for legal-section retrieval."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.config import settings
from app.services.embeddings import embed_text


@lru_cache
def _qdrant_client():
    from qdrant_client import QdrantClient
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)


@lru_cache
def _pinecone_index():
    from pinecone import Pinecone
    kwargs = {"api_key": settings.pinecone_api_key}
    if settings.pinecone_host:
        kwargs["host"] = settings.pinecone_host
    pc = Pinecone(**kwargs)

    if settings.pinecone_host:
        # Pinecone Local assigns each index its own data-plane port (e.g. localhost:5081).
        # The SDK requires the host to contain a dot or 'localhost'.
        # We use host.docker.internal (which resolves to the host machine from within Docker)
        # so the port-mapped pinecone-local container is reachable.
        from urllib.parse import urlparse
        info = pc.describe_index(settings.pinecone_index)
        idx_parsed = urlparse(info.host)
        # Rewrite to host.docker.internal so Docker Desktop routing works
        index_host = f"http://host.docker.internal:{idx_parsed.port}"
        return pc.Index(settings.pinecone_index, host=index_host)

    return pc.Index(settings.pinecone_index)


async def search_sections(
    query: str,
    *,
    top_k: int = 5,
    section_number: str | None = None,
    filters: dict[str, Any] | None = None,
    acts: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return relevant legal sections using the active vector store provider."""
    provider = (settings.vector_store_provider or "qdrant").lower()
    if provider == "pinecone":
        return await _search_sections_pinecone(
            query, top_k=top_k, section_number=section_number, filters=filters, acts=acts
        )
    else:
        return await _search_sections_qdrant(
            query, top_k=top_k, section_number=section_number, filters=filters, acts=acts
        )

async def search_case_laws(
    query: str,
    *,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """Return relevant historical cases from the case_laws vector store."""
    provider = (settings.vector_store_provider or "qdrant").lower()
    if provider == "pinecone":
        return await _search_case_laws_pinecone(query, top_k=top_k)
    else:
        return await _search_case_laws_qdrant(query, top_k=top_k)


async def _search_sections_qdrant(
    query: str,
    top_k: int = 5,
    section_number: str | None = None,
    filters: dict[str, Any] | None = None,
    acts: list[str] | None = None,
) -> list[dict[str, Any]]:
    from qdrant_client.http import models

    client = _qdrant_client()
    must_conditions = []
    
    if filters:
        for k, v in filters.items():
            must_conditions.append(models.FieldCondition(key=k, match=models.MatchValue(value=v)))

    if section_number:
        must_conditions.append(models.FieldCondition(key="section_number", match=models.MatchValue(value=section_number)))
        
    if acts:
        cleaned = [a.strip().upper() for a in acts if a]
        if cleaned:
            if len(cleaned) == 1:
                must_conditions.append(models.FieldCondition(key="act", match=models.MatchValue(value=cleaned[0])))
            else:
                must_conditions.append(models.FieldCondition(key="act", match=models.MatchAny(any=cleaned)))

    query_filter = models.Filter(must=must_conditions) if must_conditions else None

    if section_number or not query.strip():
        vector = [1e-6] * settings.embeddings_dim
    else:
        vector = await embed_text(query)

    result = client.search(
        collection_name=settings.qdrant_collection,
        query_vector=vector,
        limit=top_k,
        query_filter=query_filter,
        with_payload=True
    )

    out: list[dict[str, Any]] = []
    for m in result:
        payload = m.payload or {}
        out.append({
            "score": m.score,
            "act": payload.get("act", ""),
            "category": payload.get("category", ""),
            "section_number": str(payload.get("section_number", "")),
            "section_title": payload.get("section_title", ""),
            "text": payload.get("pageContent") or payload.get("text", ""),
        })
    return out


async def _search_sections_pinecone(
    query: str,
    top_k: int = 5,
    section_number: str | None = None,
    filters: dict[str, Any] | None = None,
    acts: list[str] | None = None,
) -> list[dict[str, Any]]:
    index = _pinecone_index()
    pinecone_filters = {}

    if filters:
        for k, v in filters.items():
            pinecone_filters[k] = v

    if section_number:
        pinecone_filters["section_number"] = section_number

    if acts:
        cleaned = [a.strip().upper() for a in acts if a]
        if cleaned:
            if len(cleaned) == 1:
                pinecone_filters["act"] = cleaned[0]
            else:
                pinecone_filters["act"] = {"$in": cleaned}

    if section_number or not query.strip():
        vector = [1e-6] * settings.embeddings_dim
    else:
        vector = await embed_text(query)

    res = index.query(
        vector=vector,
        top_k=top_k * 3,  # query more to account for deduping
        filter=pinecone_filters if pinecone_filters else None,
        include_metadata=True,
    )

    out: list[dict[str, Any]] = []
    seen = set()
    for m in (res.matches or []):
        meta = m.metadata or {}
        num = str(meta.get("section_number", ""))
        act = meta.get("act", "")
        key = f"{act}_{num}"
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "score": m.score,
            "act": act,
            "category": meta.get("category", ""),
            "section_number": num,
            "section_title": meta.get("section_title", ""),
            "text": meta.get("pageContent") or meta.get("text", ""),
        })
        if len(out) >= top_k:
            break
    return out


async def _search_case_laws_qdrant(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    from qdrant_client.http import models
    client = _qdrant_client()
    
    if not query.strip():
        vector = [1e-6] * settings.embeddings_dim
    else:
        vector = await embed_text(query)

    try:
        result = client.search(
            collection_name=settings.qdrant_case_laws_collection,
            query_vector=vector,
            limit=top_k,
            with_payload=True
        )
    except Exception:
        return [] # Collection might not exist yet

    out: list[dict[str, Any]] = []
    for m in result:
        payload = m.payload or {}
        out.append({
            "score": m.score,
            "title": payload.get("title", ""),
            "court": payload.get("court", ""),
            "year": payload.get("year", ""),
            "disposition": payload.get("disposition", ""),
            "snippet": payload.get("snippet", ""),
            "summary": payload.get("summary", ""),
            "source_pdf_s3_url": payload.get("source_pdf_s3_url", ""),
            "text": payload.get("text", ""),
        })
    return out


async def _search_case_laws_pinecone(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    from pinecone import Pinecone
    pc = Pinecone(api_key=settings.pinecone_api_key)
    try:
        index = pc.Index(settings.pinecone_case_laws_index)
    except Exception:
        return []
        
    if not query.strip():
        vector = [1e-6] * settings.embeddings_dim
    else:
        vector = await embed_text(query)

    try:
        res = index.query(
            vector=vector,
            top_k=top_k,
            include_metadata=True,
        )
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    for m in (res.matches or []):
        meta = m.metadata or {}
        out.append({
            "score": m.score,
            "title": meta.get("title", ""),
            "court": meta.get("court", ""),
            "year": meta.get("year", ""),
            "disposition": meta.get("disposition", ""),
            "snippet": meta.get("snippet", ""),
            "summary": meta.get("summary", ""),
            "source_pdf_s3_url": meta.get("source_pdf_s3_url", ""),
            "text": meta.get("text", ""),
        })
    return out

