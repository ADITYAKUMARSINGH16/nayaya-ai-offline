-- ============================================================================
-- Migration 003 — `evidence` table for files uploaded against an investigation.
--
-- The Police page already uploads to Supabase Storage. This table stores the
-- (investigation/fir, storage_path, filename, ...) so the file is findable
-- after refresh + shows up on the investigation card.
--
-- Apply via Supabase SQL editor. Idempotent.
-- ============================================================================

create table if not exists public.evidence (
    id               uuid primary key default gen_random_uuid(),
    investigation_id uuid references public.investigations(id) on delete cascade,
    fir_id           uuid references public.fir_records(id)    on delete set null,
    user_id          uuid references auth.users(id)            on delete cascade,
    storage_path     text not null,
    filename         text not null,
    mime_type        text,
    size_bytes       bigint,
    description      text,
    uploaded_at      timestamptz not null default now()
);

create index if not exists evidence_investigation_idx on public.evidence(investigation_id, uploaded_at desc);
create index if not exists evidence_fir_idx           on public.evidence(fir_id, uploaded_at desc);
create index if not exists evidence_user_idx          on public.evidence(user_id, uploaded_at desc);

alter table public.evidence enable row level security;

do $$ begin
  drop policy if exists "evidence owner all" on public.evidence;
end $$;
create policy "evidence owner all" on public.evidence
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
