# Terminal Command History

Here is a log of all the terminal commands we ran during this session, along with what each one accomplished:

### 1. Rebuilding the Frontend Container
Used to rebuild just the frontend after we fixed the `SecretsUsedInArgOrEnv` warnings in the Dockerfile.

```bash
# Attempted to rebuild frontend (failed due to a conflict with the backend container name)
docker compose up -d --build frontend

# Successfully rebuilt strictly the frontend without touching dependencies
docker compose up -d --build --no-deps frontend
```

### 2. Applying Supabase Migrations
Used to apply the new `005_evidence_bucket.sql` migration that created the missing `evidence` storage bucket.

```bash
# Checked if the global supabase CLI was installed (it wasn't)
supabase --version

# Used npx to run the local supabase CLI and apply migrations
npx supabase migration up
```

### 3. Seeding Vector Stores
Used to generate embeddings and populate the vector databases with data from `data/sections_enriched.json`.

```bash
# Command to seed Pinecone (you denied this execution to avoid the --reset flag)
docker exec -w /app nyaya-backend python -m scripts.seed_pinecone_v3 --reset

# Command to safely seed Pinecone without wiping it first
docker exec -w /app nyaya-backend python -m scripts.seed_pinecone_v3

# Command we ran to seed the newly created script for Qdrant
docker exec -w /app nyaya-backend python -m scripts.seed_qdrant_full
```

### 4. Restarting Containers
Used to quickly restart the containers so they would pick up changes made to the `.env` file (like switching the `OLLAMA_MODEL` and `VECTOR_STORE_PROVIDER`).

```bash
docker compose up -d
```


After model change 
docker restart nyaya-backend
docker compose up -d --build backend

docker compose up -d --build frontend



for evaluation run this command
docker compose exec backend python -m eval.runner
