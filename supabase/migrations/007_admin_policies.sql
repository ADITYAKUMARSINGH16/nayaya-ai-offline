-- ============================================================================
-- Migration 007 — Admin Policies and Functions
-- ============================================================================

-- Create a security definer function to securely check if the current user is an admin
create or replace function public.is_admin()
returns boolean as $$
  select exists (
    select 1 from public.profiles
    where id = auth.uid() and role = 'admin'
  );
$$ language sql security definer;

-- Add admin policies to the profiles table
drop policy if exists "Admins can select all profiles" on public.profiles;
create policy "Admins can select all profiles"
  on public.profiles for select
  to authenticated
  using (public.is_admin());

drop policy if exists "Admins can update all profiles" on public.profiles;
create policy "Admins can update all profiles"
  on public.profiles for update
  to authenticated
  using (public.is_admin());

-- Add admin policy to the cases table for counting
drop policy if exists "Admins can select all cases" on public.cases;
create policy "Admins can select all cases"
  on public.cases for select
  to authenticated
  using (public.is_admin());

-- Also allow admins to see all users in auth.users so we can join their emails if needed
-- Note: auth.users is usually restricted by Supabase, but we can rely on our `profiles` table
-- since we added an `email` column in migration 001. Wait, 001 has an email column, 
-- but 006 replaced the trigger. Let's make sure our 006 trigger handles email if needed.
-- Actually, the 001 trigger was replaced by 006 trigger which only inserts id and role.
-- But wait, we can just use `profiles` table to see the IDs and roles. 
-- In our dashboard, we will just count profiles.
