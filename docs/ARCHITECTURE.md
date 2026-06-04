# Architecture

## Components

| Component  | Tech | Responsibility |
|------------|------|----------------|
| Frontend   | React 18, Vite, Tailwind, Framer Motion, React Router 6, React Query, Recharts, Supabase JS | UI + Supabase auth + SSE streaming + PDF print |
| Backend    | FastAPI, Pydantic v2, httpx, python-jose, sse-starlette, rank-bm25 | Multi-agent orchestration, hybrid RAG, citation verification, JWT auth |
| LLM        | Groq / OpenAI / Ollama (swappable) — all with streaming | Generation for every agent |
| Embeddings | Ollama `nomic-embed-text` (default 768-dim) | RAG retrieval |
| Vector     | Pinecone `rag-legal` index | Legal-section retrieval |
| Graph      | `data/legal_graph.json` (LegalGraph-Lite, mounted volume) | Statute cross-reference adjacency |
| DB + Auth  | Supabase (Postgres + Auth + RLS) | Users, chat, FIRs, investigations, cases, evals |
| Automation | n8n (6 workflows) | Webhooks, human-in-the-loop, cron, error handling |

## End-to-end flow — a verdict

```
[ User in browser ]
    │  POST /api/cases/trial   (JWT in Authorization header)
    ▼
[ FastAPI: routers/cases.py ]
    │  Depends(get_current_user) → derive user_id from JWT
    ▼
[ agents/courtroom.py — run_trial() ]
    │
    ├──► services/rag.retrieve_context()  ⇩
    │       1. detect metadata hints (act / category)
    │       2. vector search Pinecone with filter  →  seeds
    │       3. legal_graph.expand_seed_sections(seeds, hops=1)  →  graph neighbours
    │       4. BM25 over merged pool
    │       5. RRF fuse (vector ▢ BM25 ▢ graph)  →  top N
    │       6. return {context, citations}
    │
    ├──► PETITIONER agent   ──► get_llm().complete_json()
    ├──► OPPOSING   agent   (× N rounds)
    ├──► REBUTTAL   agent
    ├──► JUDGE      agent   →   Judgment (structured)
    │
    ├──► agents/verifier.verify_text(judgment)
    │     └─► for each Section N cited:
    │            re-retrieve actual statute text from Pinecone
    │            ask Verifier LLM "does it support the claim?"
    │            tag Citation with verified=true/false + note
    │
    └──► services/db.create_case / update_case   (Supabase, RLS-scoped)

[ routers/cases.py ]
    └──► services/n8n.notify_verdict(payload)   →   /webhook/case-notify  (n8n fan-out)

[ Frontend (TrialPage) ]
    renders 4 staggered CourtPanels + verdict card + verified citation cards
```

## LegalGraph-Lite — the cheap GraphRAG

Full GraphRAG (Microsoft-style entity extraction + Neo4j) is expensive at
ingest and infra. LegalGraph-Lite captures the same signal **for free** by
exploiting structure already present in the corpus:

- **Regex cross-references** in section text (`section\s*\d+`, `subject to …`,
  `as defined in section …`). One pass, no LLM cost.
- **Metadata co-membership edges** (same `act` + `category`) — capped at small
  buckets to avoid linking everything.

The result lives in `data/legal_graph.json`:

```json
{
  "sections": { "303": {"title": "Theft", "act": "BNS", ...}, ... },
  "edges":    { "303": ["305", "318", ...], ... }
}
```

Retrieval is then **hybrid**:

```
vector (semantic) ──┐
graph (1-hop)    ──┼──► RRF fuse ──► top N
BM25  (lexical)  ──┘
```

Why each layer matters:
- Vector finds *semantically related* sections.
- Graph pulls in sections the seed *explicitly references* (multi-hop legal
  reasoning) that pure semantics may miss.
- BM25 catches *exact-term* queries ("section 351", "house trespass") the
  vector store can rank below.
- RRF is parameter-free and unbiased — perfect when you don't want to tune.

## Citation verifier — the trust layer

Every agent argues using sections from RAG context, but the model may still
hallucinate or misapply a section. After the judge rules:

1. Extract every `Section N` mentioned in the judgment + applicable_sections.
2. Re-query Pinecone with a metadata filter on `section_number=N` to get the
   **actual statute text**.
3. Ask the LLM (small/fast model): *"does this section text support the
   claim?"* — strict JSON `{verified, note}`.
4. Return a `Citation[]` where each entry carries `verified: true|false`
   and a one-sentence rationale. The UI badges them green / red.

## n8n integration map

| Trigger | Workflow | What |
|---------|----------|------|
| Backend after every verdict (`services/n8n.notify_verdict`) | `case-notify-fanout` | Fan out to Email / Slack / Telegram / WhatsApp |
| Backend when `N8N_FIR_APPROVAL=true` (`services/n8n.request_fir_approval`) | `fir-human-approval` | `Wait` for human Approve/Reject, callback the backend |
| Cron (daily 09:00 IST) | `eval-cron` | POST `/api/admin/run-eval` (X-Internal-Key) → write `eval_runs` |
| Cron (weekly Sun 03:00 IST) | `graph-rebuild-cron` | POST `/api/admin/rebuild-graph` |
| Webhook (Execute Workflow optional) | `agent-petitioner` | Petitioner role as a callable n8n sub-workflow |
| Any of the above on error | `error-handler` | Format + alert admin |

## Why FastAPI *and* n8n?

- **FastAPI** owns *core reasoning* — agents, RAG, verifier, JWT. Python
  code in version control, testable, easy to iterate.
- **n8n** owns *integration glue* — multi-channel notifications, scheduled
  jobs, human-in-the-loop approval, error fan-out. This is what n8n is
  genuinely good at; using it here is honest, not a marketing tick.

## Data contracts

All requests/responses are typed via Pydantic models in
[`backend/app/schemas/models.py`](../backend/app/schemas/models.py).
The frontend's [`api/client.js`](../frontend/src/api/client.js) calls these
endpoints directly. One source of truth per domain (Assistant, FIR,
Investigation, Trial).

## Auth model

- **Frontend**: Supabase Auth issues a JWT, stored in browser memory by
  `@supabase/supabase-js`. Every API call attaches `Authorization: Bearer <jwt>`.
- **Backend**: `core/security.get_current_user` verifies the HS256
  signature with `SUPABASE_JWT_SECRET` and exposes `CurrentUser(id, email,
  is_admin)` to every route via `Depends`.
- **n8n → admin endpoints**: shared `ADMIN_INTERNAL_KEY` header
  (`X-Internal-Key`). No long-lived JWT to leak.
