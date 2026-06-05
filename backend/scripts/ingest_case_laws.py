"""Script to ingest Indian Case Laws into the vector store for AI Judge Precedents."""

import asyncio
import os
import sys

# Ensure backend directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datasets import load_dataset
from app.config import settings
from app.services.embeddings import embed_texts
from app.services.vector_store import _qdrant_client, _pinecone_index
import uuid

async def ingest_batch(batch, provider):
    """Embed and upsert a batch of case laws."""
    texts_to_embed = []
    metadata_list = []
    ids = []

    for item in batch:
        # Create a text representation for embedding
        case_title = item.get("case_title") or "Unknown Case"
        headnote = item.get("headnote_text") or item.get("disposition_text") or ""
        court = item.get("court_name") or "Unknown Court"
        year = str(item.get("decision_year") or "Unknown")
        
        # Only embed if there's substantial text to embed
        if not headnote.strip():
            # If no headnote or disposition, use the title and court
            headnote = f"Case from {court} regarding {case_title}"

        text = f"Title: {case_title}\nCourt: {court}\nYear: {year}\nSummary: {headnote}"
        texts_to_embed.append(text)
        
        # Generate a unique ID (or use case_metadata_id if available)
        doc_id = str(item.get("id") or uuid.uuid4())
        ids.append(doc_id)
        
        metadata = {
            "title": case_title,
            "court": court,
            "year": year,
            "disposition": str(item.get("disposition_text") or ""),
            "snippet": headnote[:500] + ("..." if len(headnote) > 500 else ""),
            "text": text,
        }
        metadata_list.append(metadata)

    if not texts_to_embed:
        return

    print(f"Embedding {len(texts_to_embed)} cases...")
    vectors = await embed_texts(texts_to_embed)

    print(f"Upserting {len(vectors)} vectors to {provider}...")
    if provider == "pinecone":
        index = _pinecone_index() # Wait, pinecone index is hardcoded to settings.pinecone_index in vector_store.py
        # Need to fix that to allow passing index name or we assume it's set in env.
        # But for script, we can just use the Pinecone client directly
        from pinecone import Pinecone
        pc = Pinecone(api_key=settings.pinecone_api_key)
        idx = pc.Index(settings.pinecone_case_laws_index)
        
        upsert_data = []
        for i, doc_id in enumerate(ids):
            upsert_data.append((doc_id, vectors[i], metadata_list[i]))
        idx.upsert(vectors=upsert_data)
        
    else:
        # Qdrant
        client = _qdrant_client()
        from qdrant_client.http import models
        
        points = []
        for i, doc_id in enumerate(ids):
            points.append(
                models.PointStruct(
                    id=doc_id if "-" in doc_id else str(uuid.uuid4()), # Qdrant needs UUID format
                    vector=vectors[i],
                    payload=metadata_list[i]
                )
            )
        client.upsert(
            collection_name=settings.qdrant_case_laws_collection,
            points=points
        )

async def main():
    # If running natively on Windows/host, 'qdrant' and 'host.docker.internal' won't resolve.
    # We replace them with localhost.
    import socket
    try:
        socket.gethostbyname("qdrant")
    except socket.gaierror:
        print("Host 'qdrant' not found. Overriding QDRANT_URL to localhost...")
        settings.qdrant_url = settings.qdrant_url.replace("qdrant", "localhost")
        
    try:
        socket.gethostbyname("host.docker.internal")
    except socket.gaierror:
        print("Host 'host.docker.internal' not found. Overriding OLLAMA_BASE_URL to localhost...")
        settings.ollama_base_url = settings.ollama_base_url.replace("host.docker.internal", "localhost")

    provider = (settings.vector_store_provider or "qdrant").lower()
    print(f"Using vector store provider: {provider}")

    # Initialize collection if using Qdrant
    if provider == "qdrant":
        client = _qdrant_client()
        from qdrant_client.http import models
        try:
            client.get_collection(settings.qdrant_case_laws_collection)
            print(f"Collection {settings.qdrant_case_laws_collection} exists.")
        except Exception:
            print(f"Creating collection {settings.qdrant_case_laws_collection}...")
            client.create_collection(
                collection_name=settings.qdrant_case_laws_collection,
                vectors_config=models.VectorParams(
                    size=settings.embeddings_dim,
                    distance=models.Distance.COSINE
                )
            )

    print("Loading Indian Case Laws dataset...")
    # Streaming allows us to not download the whole dataset at once
    dataset = load_dataset("KanoonGPT/indian-case-laws", data_dir="structured/v1", split="train", streaming=True)
    
    # We will process in batches of 100
    batch = []
    batch_size = 100
    count = 0

    for item in dataset:
        # Include ONLY Supreme Court cases
        court = item.get("court_name") or ""
        court_lower = court.lower()
        if "supreme court" not in court_lower:
            continue

        batch.append(item)
        if len(batch) >= batch_size:
            await ingest_batch(batch, provider)
            count += len(batch)
            batch = []
            print(f"Ingested {count} cases so far.")
                
    if batch:
        await ingest_batch(batch, provider)
        count += len(batch)

    print(f"Finished ingesting {count} cases.")

if __name__ == "__main__":
    asyncio.run(main())
