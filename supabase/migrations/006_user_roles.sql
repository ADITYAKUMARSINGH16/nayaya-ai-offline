-- ============================================================================
-- Migration 006 — `profiles` table for RBAC
-- ============================================================================

create type public.app_role as enum ('user', 'admin', 'lawyer', 'police', 'judge');

create table if not exists public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    role public.app_role not null default 'user',
    created_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

-- Policy to allow users to read their own profile
create policy "Users can read own profile"
on public.profiles for select
to authenticated
using ( auth.uid() = id );

-- Function to handle new user signup and extract role from metadata
create or replace function public.handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id, email, role)
  values (
    new.id,
    new.email,
    coalesce((new.raw_user_meta_data->>'role')::public.app_role, 'user'::public.app_role)
  )
  on conflict (id) do update set 
    email = excluded.email,
    role = excluded.role;
  return new;
end;
$$ language plpgsql security definer;

-- Trigger to create profile when auth.user is created
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

-- Backfill profiles for any existing users
insert into public.profiles (id, role)
select id, 'user'::public.app_role from auth.users
on conflict (id) do nothing;
