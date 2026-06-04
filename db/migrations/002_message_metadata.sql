-- ============================================================================
-- Migration 002 — store per-message metadata (citations, intent, confidence).
--
-- Apply via Supabase SQL editor (same as 001). Idempotent.
-- ============================================================================

alter table public.chat_history
  add column if not exists metadata jsonb;

-- Useful when the frontend loads a past conversation and wants the citations
-- back without re-running RAG.
comment on column public.chat_history.metadata is
  'Optional per-message metadata. For assistant messages we store: '
  '{ citations: [...], low_confidence: bool, intent: "LEGAL"|"GREETING"|... }';
