# Local Docker Migration Walkthrough

The project has been successfully migrated to run entirely on your local machine using Docker! I have replaced all cloud-managed external dependencies with local Dockerized equivalents.

## Changes Made

### 1. Vector Store (Pinecone -> Qdrant)
- **Qdrant Integration:** Replaced Pinecone with Qdrant, a fast open-source vector store that runs natively in Docker.
- **Backend Refactoring:** Completely rewrote `backend/app/services/vector_store.py` to use `qdrant-client`. It supports the same vector search and metadata filtering techniques previously used by Pinecone.
- **Seeding Script Update:** Renamed and refactored `backend/scripts/seed_pinecone.py` to `backend/scripts/seed_qdrant.py` so you can seed your legal sections straight into the local Qdrant instance.

### 2. Database & Auth (Supabase Local)
- **Supabase CLI Project:** Initialized a local Supabase project (`supabase/`).
- **Migrations Transfer:** Moved your existing database schemas from `db/migrations/` to `supabase/migrations/`. These will now automatically run when the local Supabase container starts.
- **Environment Updates:** Updated `.env.example` with the default local Supabase credentials (URL `http://127.0.0.1:54321` and standard local keys) and the local Qdrant settings.

### 3. Unified Docker Compose
- **Single Stack:** Created a unified `docker-compose.yml` that includes your `backend`, `frontend`, `n8n`, and `qdrant` services, all running under the `nyaya` bridge network.
- **Cleanup:** Deleted the fragmented `docker-compose1.yml`.

## How to Run It

To launch your fully local environment, follow these steps:

1. **Start the Database (Supabase):**
   ```bash
   npx supabase start
   ```
   > [!TIP]
   > This command spins up all the necessary Postgres and Auth containers in the background and applies your database schemas automatically.

2. **Start the Application Stack:**
   Make sure you have copied `.env.example` to `.env`, then run:
   ```bash
   docker-compose up -d --build
   ```

3. **Seed the Vector Store:**
   Populate Qdrant with the sample legal sections:
   ```bash
   docker compose exec backend python -m scripts.seed_qdrant
   ```

4. **Access the Services:**
   - **Frontend:** `http://localhost:5173`
   - **n8n:** `http://localhost:5678`
   - **Backend API:** `http://localhost:8000/docs`
   - **Supabase Studio:** `http://127.0.0.1:54323` (Database and Auth management UI)
