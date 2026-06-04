# Evaluation Methodology

Nyaya AI ships with a **labeled retrieval test set** and a **daily eval
harness** so quality is measured, not vibes.

## Test set

Lives at [`backend/eval/test_cases.json`](../backend/eval/test_cases.json).
Each item is a query + the BNS section number(s) we expect to appear in the
top-k citations:

```json
{ "query": "What is the punishment for theft?",
  "expected_sections": ["303"] }
```

Twenty-five hand-curated cases covering theft, robbery, dacoity,
trespass, hurt/grievous hurt, murder, sexual offences, cyber, family,
defamation, forgery, abetment, mischief — and a couple of direct
"section N" lookups to test the lexical path.

Adding a case is one JSON line. Optionally also seed the `test_cases`
table in Supabase (see [`db/README.md`](../db/README.md)) so the dashboard
can grow with the set.

## Metrics

Each daily run logs one row to Supabase `eval_runs`:

| Field | Definition |
|-------|------------|
| `precision_at_k` | Fraction of test cases where at least one **expected** section appears in the top-k returned citations. |
| `citation_verified_rate` | Fraction of returned citations that the verifier agent marked `verified=true`. A hallucination detector — if the model cites sections the verifier can't substantiate, this drops. |
| `latency_ms_p50` / `p95` | End-to-end response latency of the assistant endpoint. |
| `total` / `hits` | Raw counts. |
| `details` | Per-case JSON (query, returned, expected, hit?, verified_rate, latency, error). |

## How it runs

1. **Daily** at 09:00 IST, n8n workflow `eval-cron`:
   - POSTs `/api/admin/run-eval` (with `X-Internal-Key`)
   - The backend spawns `python -m eval.runner`
   - Each case POSTs `/api/assistant` and the response is scored
   - A single summary row lands in `eval_runs`
   - n8n then fetches `/api/eval/latest` and ships a digest message
2. **Manual**: `docker compose exec backend python -m eval.runner` —
   the same code path, useful while developing.

## Dashboard

`/app/eval` reads `/api/eval/runs?limit=50` and plots:
- Precision@k % over time (gold)
- Verified % over time (green)
- p50 latency over time (blue)

## Interpreting changes

- **Precision@k drops** → retrieval regressed. Suspect: embedding model
  changed, metadata routing broke, or a graph rebuild removed edges. Check
  the per-case `returned` lists in `details` for what was retrieved.
- **Verified rate drops** → model is hallucinating sections that don't
  match their text. Suspect: prompt change loosened citation discipline,
  or LLM provider/model swap.
- **p50 latency spikes** → LLM provider issue (Groq throttling?), or
  graph expansion is fetching too many neighbours. Cap `top_k * 2` in
  `rag.py` further if needed.

## Honesty notes

- This is a **retrieval-quality** metric, not a "did the AI give correct
  legal advice" metric. Generation quality is harder to score without
  expert review.
- Citation-verified-rate is an **internal consistency** check — the
  verifier itself is an LLM and can be wrong. It's still much better than
  no check at all (the citation has to be re-retrievable *and* the
  verifier has to agree it matches).
- For a research-grade evaluation, the next step is **judgment-prediction
  against real decided Indian cases** (feed facts in, see if the verdict
  matches). That requires a labeled dataset we don't ship.
