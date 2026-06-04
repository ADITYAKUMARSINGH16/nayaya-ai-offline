-- ============================================================================
-- Nyaya AI — initial schema (Supabase / Postgres)
--
-- Run this once against your Supabase project:
--   1) Open Supabase Studio → SQL Editor
--   2) Paste this file
--   3) Run
--
-- This script is idempotent: it uses IF NOT EXISTS where Postgres allows and
-- wraps policies in DO blocks so re-running it is safe.
-- ============================================================================

create extension if not exists "pgcrypto";

-- ----------------------------------------------------------------------------
-- profiles : 1-row-per-user metadata (joined to auth.users)
-- ----------------------------------------------------------------------------
create table if not exists public.profiles (
    id          uuid primary key references auth.users(id) on delete cascade,
    email       text,
    full_name   text,
    role        text not null default 'citizen',  -- citizen | lawyer | police | admin
    created_at  timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- chat_history : assistant ↔ user transcript
-- ----------------------------------------------------------------------------
create table if not exists public.chat_history (
    id          bigserial primary key,
    session_id  text not null,
    user_id     uuid references auth.users(id) on delete cascade,
    role        text not null check (role in ('user', 'assistant')),
    message     text not null,
    created_at  timestamptz not null default now()
);
create index if not exists chat_history_session_idx on public.chat_history(session_id, created_at);
create index if not exists chat_history_user_idx    on public.chat_history(user_id, created_at desc);

-- ----------------------------------------------------------------------------
-- fir_records : drafted FIRs
-- ----------------------------------------------------------------------------
create table if not exists public.fir_records (
    id                uuid primary key default gen_random_uuid(),
    user_id           uuid references auth.users(id) on delete cascade,
    session_id        text,
    complainant_name  text,
    incident_date     date,
    fir_text          text not null,
    status            text not null default 'draft',  -- draft | approved | rejected | filed
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);
create index if not exists fir_user_idx on public.fir_records(user_id, created_at desc);

-- ----------------------------------------------------------------------------
-- investigations : structured investigation reports
-- ----------------------------------------------------------------------------
create table if not exists public.investigations (
    id          uuid primary key default gen_random_uuid(),
    fir_id      uuid references public.fir_records(id) on delete set null,
    user_id     uuid references auth.users(id) on delete cascade,
    session_id  text,
    report      jsonb not null default '{}'::jsonb,
    created_at  timestamptz not null default now()
);
create index if not exists investigations_user_idx on public.investigations(user_id, created_at desc);
create index if not exists investigations_fir_idx  on public.investigations(fir_id);

-- ----------------------------------------------------------------------------
-- cases : courtroom simulations + verdicts
-- ----------------------------------------------------------------------------
create table if not exists public.cases (
    id                  uuid primary key default gen_random_uuid(),
    user_id             uuid references auth.users(id) on delete cascade,
    fir_id              uuid references public.fir_records(id) on delete set null,
    question            text not null,
    court_level         text not null default 'district',  -- district | high | supreme
    lawyer_output       jsonb,
    opponent_output     jsonb,
    rebuttal_output     jsonb,
    judgement_output    jsonb,
    status              text not null default 'open',      -- open | judged | appealed
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);
create index if not exists cases_user_idx on public.cases(user_id, created_at desc);

-- ----------------------------------------------------------------------------
-- test_cases : labeled retrieval-quality test set (seeded by /eval)
-- ----------------------------------------------------------------------------
create table if not exists public.test_cases (
    id                 bigserial primary key,
    query              text not null,
    expected_sections  text[] not null,
    active             boolean not null default true,
    created_at         timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- eval_runs : output of the daily eval cron
-- ----------------------------------------------------------------------------
create table if not exists public.eval_runs (
    id                       bigserial primary key,
    run_at                   timestamptz not null default now(),
    total                    int not null,
    hits                     int not null,
    precision_at_k           numeric not null,
    citation_verified_rate   numeric not null default 0,
    latency_ms_p50           numeric not null default 0,
    latency_ms_p95           numeric not null default 0,
    details                  jsonb
);
create index if not exists eval_runs_at_idx on public.eval_runs(run_at desc);

-- ============================================================================
-- Row-Level Security
--
-- Every user-owned table: a user can only see/modify their own rows.
-- `profiles`: same.
-- `test_cases` and `eval_runs`: read by any authenticated user, write blocked
-- (admin can use service-role key from the backend).
-- ============================================================================

alter table public.profiles       enable row level security;
alter table public.chat_history   enable row level security;
alter table public.fir_records    enable row level security;
alter table public.investigations enable row level security;
alter table public.cases          enable row level security;
alter table public.test_cases     enable row level security;
alter table public.eval_runs      enable row level security;

-- profiles
do $$ begin
  drop policy if exists "profiles self select" on public.profiles;
  drop policy if exists "profiles self update" on public.profiles;
  drop policy if exists "profiles self insert" on public.profiles;
end $$;
create policy "profiles self select" on public.profiles
  for select using (auth.uid() = id);
create policy "profiles self update" on public.profiles
  for update using (auth.uid() = id);
create policy "profiles self insert" on public.profiles
  for insert with check (auth.uid() = id);

-- generic owner-scoped policies for the rest
do $$
declare t text;
begin
  foreach t in array array['chat_history','fir_records','investigations','cases']
  loop
    execute format('drop policy if exists "%1$s owner all" on public.%1$s', t);
    execute format('create policy "%1$s owner all" on public.%1$s
                    using (auth.uid() = user_id)
                    with check (auth.uid() = user_id)', t);
  end loop;
end $$;

-- test_cases / eval_runs : authenticated read only
do $$ begin
  drop policy if exists "test_cases read" on public.test_cases;
  drop policy if exists "eval_runs read"  on public.eval_runs;
end $$;
create policy "test_cases read" on public.test_cases
  for select using (auth.role() = 'authenticated');
create policy "eval_runs read"  on public.eval_runs
  for select using (auth.role() = 'authenticated');

-- ============================================================================
-- Trigger: auto-create a profile row when a user signs up
-- ============================================================================
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, email)
  values (new.id, new.email)
  on conflict (id) do nothing;
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();
