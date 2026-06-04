-- ============================================================================
-- Migration 004 — `judgments` table preserves the full appeal chain.
--
-- Before: cases.judgement_output was overwritten when you appealed
--         (District → High → Supreme).
-- After:  each level inserts a new row here. cases.judgement_output is kept
--         as the "latest" pointer for backwards compatibility; judgments is
--         the source of truth for history + appeal-chain rendering.
--
-- Apply via Supabase SQL editor. Idempotent.
-- ============================================================================

create table if not exists public.judgments (
    id               uuid primary key default gen_random_uuid(),
    case_id          uuid not null references public.cases(id) on delete cascade,
    user_id          uuid references auth.users(id)            on delete cascade,
    court_level      text not null check (court_level in ('district','high','supreme')),
    petitioner_output jsonb,
    opponent_output  jsonb,
    rebuttal_output  jsonb,
    judgment         jsonb not null,
    citations        jsonb,
    created_at       timestamptz not null default now()
);

create index if not exists judgments_case_idx on public.judgments(case_id, created_at);
create index if not exists judgments_user_idx on public.judgments(user_id, created_at desc);

-- A given case has at most ONE judgment per court level. Re-running a trial
-- at the same level should upsert, not insert duplicate rows.
create unique index if not exists judgments_case_level_unique
  on public.judgments(case_id, court_level);

alter table public.judgments enable row level security;

do $$ begin
  drop policy if exists "judgments owner all" on public.judgments;
end $$;
create policy "judgments owner all" on public.judgments
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
