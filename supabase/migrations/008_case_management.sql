-- ============================================================================
-- Migration 008 — Case Management extensions for Judges and Lawyers
-- ============================================================================

-- Add new columns to `cases` table
alter table public.cases
    add column if not exists assigned_lawyer uuid references auth.users(id) on delete set null,
    add column if not exists assigned_judge uuid references auth.users(id) on delete set null,
    add column if not exists case_status text not null default 'draft', -- draft | filed | investigation | trial | awaiting_verdict | closed
    add column if not exists human_verdict jsonb,
    add column if not exists human_verdict_status text; -- approved | rejected | modified

-- Create indexes for the new assignment columns
create index if not exists cases_lawyer_idx on public.cases(assigned_lawyer);
create index if not exists cases_judge_idx on public.cases(assigned_judge);

-- Update RLS policies to allow lawyers and judges to see cases
do $$ begin
  drop policy if exists "cases owner all" on public.cases;
  drop policy if exists "cases lawyer read" on public.cases;
  drop policy if exists "cases lawyer update" on public.cases;
  drop policy if exists "cases judge read" on public.cases;
  drop policy if exists "cases judge update" on public.cases;
end $$;

-- Owner can read and update their own cases
create policy "cases owner all" on public.cases
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

-- Lawyers can read cases they are assigned to, or maybe all cases if we want an open pool?
-- Let's allow lawyers and judges to read ALL cases so they can claim them.
create policy "cases lawyer read" on public.cases
    for select
    using (
        exists (
            select 1 from public.profiles
            where id = auth.uid() and role = 'lawyer'
        )
    );

create policy "cases lawyer update" on public.cases
    for update
    using (
        exists (
            select 1 from public.profiles
            where id = auth.uid() and role = 'lawyer'
        )
    );

create policy "cases judge read" on public.cases
    for select
    using (
        exists (
            select 1 from public.profiles
            where id = auth.uid() and role = 'judge'
        )
    );

create policy "cases judge update" on public.cases
    for update
    using (
        exists (
            select 1 from public.profiles
            where id = auth.uid() and role = 'judge'
        )
    );
