# Nyaya AI

> **AI-powered Indian legal reasoning & trial simulation** — grounded in
> **Bharatiya Nyaya Sanhita 2023**, **Bharatiya Nagarik Suraksha Sanhita 2023**
> and **Bharatiya Sakshya Adhiniyam 2023**.

A complete, dockerized, multi-agent system that takes a citizen's complaint all
the way to a reasoned trial-court verdict — with every cited section
**re-verified** against the actual statute by a dedicated audit agent, and a
**LegalGraph-Lite** retrieval layer that follows statute cross-references the
way a real lawyer would.

```
┌─────────────────┐    ┌──────────────────────────────────────────────┐    ┌──────────────┐
│  Frontend       │    │  Backend (FastAPI)                           │    │  Cloud data  │
│  React + Vite   │◄──►│  Assistant · FIR · Police · Trial            │◄──►│  Supabase    │
│  Tailwind       │    │  Citation Verifier · Hybrid + GraphLite RAG  │    │  Pinecone    │
│  Streaming SSE  │    │  Swappable LLM (Groq/OpenAI/Ollama)          │    └──────────────┘
└─────────────────┘    └──────────────────────────────────────────────┘
                                       ▲
                                       │  webhooks · cron · approvals
                                       ▼
                       ┌──────────────────────────────────────────────┐
                       │  n8n  (6 workflows: notify · approve · eval  │
                       │         cron · graph rebuild · agent · error)│
                       └──────────────────────────────────────────────┘
```

---

## ✨ What's distinctive

1. **LegalGraph-Lite** — a cheap, no-Neo4j knowledge graph over BNS/BNSS/BSA
   sections, built from regex cross-references + metadata. Vector search
   finds seed sections; the graph expands to 1-hop neighbours; BM25 catches
   exact terms; **Reciprocal Rank Fusion** merges all three. Captures the
   structural signal of legal text that plain top-k vector search misses.
2. **Citation verifier agent** — for every section the AI judge cites, the
   real statute text is re-retrieved and a verifier agent rules whether the
   claim actually matches the statute. Each verdict ships with
   **Verified / Unverified** trust badges. This is the trust layer that plain
   LLM legal tools lack.
3. **Multi-round agentic courtroom** — Petitioner → Defence → Rebuttal
   repeats up to 3 rounds before the Judge rules. Full appeal chain:
   District → High → Supreme.
4. **Swappable LLM provider** — Groq · OpenAI · Ollama via one env var.
   Streaming chat works on every provider.
5. **Hybrid backend** — FastAPI for the heavy reasoning (testable, in code);
   **n8n at six real integration points** — human-in-the-loop FIR approval,
   verdict fan-out, daily eval cron, weekly graph rebuild, role-as-subworkflow
   demo, central error handler.
6. **Hardened** — Supabase JWT verification on every endpoint, RLS policies,
   SQL migrations, JSON-repair retry, pytest suite, evaluation dashboard.
7. **Polished UI** — judicial dark/light theme, glass cards, streaming chat,
   animated court panels, PDF/print export, evidence upload, mobile drawer.
8. **Fully dockerized** — `docker compose up` brings up the entire stack.

---

## 📁 Project layout

```
nyaya-ai/
├── docker-compose.yml                # 3 services: backend, frontend, n8n
├── .env.example                      # every knob, no real secrets
├── data/                             # mounted volume — holds legal_graph.json
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py                   # FastAPI app + routes
│       ├── config.py                 # env-driven settings
│       ├── core/
│       │   ├── llm/                  # swappable LLM (Groq / OpenAI / Ollama) — with streaming
│       │   └── security.py           # Supabase JWT auth dep
│       ├── services/
│       │   ├── rag.py                # hybrid: vector + BM25 + graph + RRF
│       │   ├── legal_graph.py        # LegalGraph-Lite build + query
│       │   ├── rerank.py             # BM25 + RRF
│       │   ├── vector_store.py       # Pinecone access
│       │   ├── embeddings.py
│       │   ├── n8n.py                # webhook client (fire-and-forget)
│       │   └── db.py                 # Supabase persistence
│       ├── prompts/templates.py      # all agent system prompts
│       ├── agents/                   # assistant, fir, police, courtroom, verifier
│       ├── routers/                  # assistant (+stream), fir, police, cases, admin, eval, health
│       └── schemas/models.py         # shared pydantic contracts
├── backend/scripts/build_graph.py    # one-shot LegalGraph-Lite ingest
├── backend/eval/                     # test set + runner.py (writes Supabase eval_runs)
├── backend/tests/                    # pytest suite
├── frontend/                         # React 18 + Vite + Tailwind + Framer Motion
│   ├── Dockerfile                    # multi-stage: build → nginx
│   ├── nginx.conf                    # static + /api proxy
│   └── src/
│       ├── pages/                    # Landing, Login, Dashboard, Assistant (streaming), FIR (PDF),
│       │                             # Police (evidence upload), Trial (animated), History, Eval (Recharts)
│       ├── components/               # CourtPanel, CitationCard, Skeleton, MobileDrawer, Disclaimer, layout, ui
│       ├── api/client.js             # API + assistantStream (SSE)
│       ├── lib/sse.js                # tiny SSE-over-POST client
│       ├── context/AuthContext.jsx   # Supabase auth (demo fallback)
│       └── print.css                 # clean A4 print stylesheet
├── n8n/workflows/                    # six importable production workflows + README
├── db/migrations/001_init.sql        # all DDL + RLS + trigger
└── docs/
    ├── ARCHITECTURE.md
    └── EVALUATION.md
```

---

## 🚀 Quick start

### 1. Configure environment

```bash
cp .env.example .env
# Fill the required vars at minimum:
#   GROQ_API_KEY=…
#   PINECONE_API_KEY=…   PINECONE_INDEX=rag-legal
#   SUPABASE_URL=…   SUPABASE_ANON_KEY=…   SUPABASE_SERVICE_KEY=…   SUPABASE_JWT_SECRET=…
#   ADMIN_INTERNAL_KEY=…  (long random string — n8n uses it to hit /api/admin/*)
#   ADMIN_EMAILS=you@example.com
```

### 2. Apply the database schema

Open Supabase Studio → SQL editor → paste & run [`db/migrations/001_init.sql`](db/migrations/001_init.sql).
Creates tables, FKs, RLS policies, and an auto-profile trigger.
See [db/README.md](db/README.md) for details.

### 3. Bring up the stack

```bash
docker compose up --build
```

| Service        | URL                              |
|----------------|----------------------------------|
| Frontend       | http://localhost:5173            |
| Backend API    | http://localhost:8000            |
| Swagger docs   | http://localhost:8000/docs       |
| Health check   | http://localhost:8000/api/health |
| n8n            | http://localhost:5678            |

### 4. Build the LegalGraph (one-time)

After the backend is healthy and your Pinecone index has the statute sections:

```bash
docker compose exec backend python -m scripts.build_graph
```

This writes `data/legal_graph.json` (mounted volume). The weekly n8n cron
[`graph-rebuild-cron`](n8n/workflows/graph-rebuild-cron.json) refreshes it
automatically.

### 5. Import the n8n workflows

Open <http://localhost:5678>, sign up for the local owner account, then
**Workflows → Import from File** for each `.json` under [n8n/workflows/](n8n/workflows/).
Activate after wiring your outbound nodes. See [n8n/workflows/README.md](n8n/workflows/README.md).

### 6. Use the app

1. **http://localhost:5173** → Sign up.
2. **Assistant** — ask a legal question, watch the answer stream and the
   citation panel populate (incl. graph-expanded neighbours).
3. **FIR** — fill the form, generate, **Print → Save as PDF**.
4. **Investigation** — paste the FIR, upload evidence files.
5. **Trial** — pick a court level + debate rounds, run the trial, see all
   four agents render with verified citations. Click **Appeal** to escalate.
6. **Eval Dashboard** — once the daily cron has produced runs, see
   precision@k / verified-rate / latency trends.

---

## 🧪 Tests

```bash
docker compose exec backend pytest -q
```

Covers JSON repair, the graph builder, the verifier extractor, and the
RRF reranker.

## 📊 Running an eval manually

```bash
docker compose exec backend python -m eval.runner
```

Or trigger via n8n: open the `eval-cron` workflow → **Execute Workflow**.
Results land in Supabase `eval_runs` and show up on the Eval Dashboard.

## 🔄 Switching LLM provider

Three drop-in providers behind one interface (`backend/app/core/llm/`):

| Provider | Default model    | Notes                                                    |
|----------|------------------|----------------------------------------------------------|
| `groq`   | `llama-3.3-70b-versatile` | Free tier, very fast — best for live demos.     |
| `openai` | **`gpt-5-nano`** | Cheapest GPT-5 tier; swap to `gpt-5-mini` or `gpt-5` for smarter (slower) replies. Legacy `gpt-4o-mini` / `gpt-4o` still work. |
| `ollama` | `llama3.1`       | Fully offline, no API key — needs a beefy local machine. |

In `.env`:

```
LLM_PROVIDER=openai          # or groq | ollama
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5-nano      # gpt-5 | gpt-5-mini | gpt-5-nano | gpt-4o-mini | …
OPENAI_FAST_MODEL=gpt-5-nano # used by classifier/verifier calls
```

Restart the backend (`docker compose restart backend`). Streaming works on
every provider — the active model is shown live in the top-bar of the app.

---

## 🔐 Security notes

- The browser holds only the Supabase **anon** key (for auth). The backend
  uses the **service-role** key, never exposed to the browser.
- Set `AUTH_REQUIRED=true` in `.env` for prod — every API call must include
  a verified Supabase JWT.
- Row-Level Security is enabled in `001_init.sql`; users can only read /
  write their own rows.
- n8n admin cron jobs call backend `/api/admin/*` with a shared
  `X-Internal-Key` (`ADMIN_INTERNAL_KEY` env var) — no long-lived JWT needed.

## ⚖️ Ethics & disclaimer

This is an **educational research project**. It does not replace a qualified
Indian legal practitioner. AI-drafted documents must always be reviewed by a
human before any official use. Every AI surface in the app shows a visible
disclaimer.

---

## 🗺 Where to next

- Hindi + English (multilingual) UI and prompts.
- Streaming the trial pipeline (per-agent SSE updates as each one finishes).
- Precedent retrieval over your own growing case database.
- Judgment-prediction evaluation against a labelled set of real decided cases.
- CI/CD beyond the smoke tests.
