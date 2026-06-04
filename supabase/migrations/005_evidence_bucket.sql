-- ============================================================================
-- Migration 005 — `evidence` storage bucket
--
-- Creates the Supabase Storage bucket for storing uploaded evidence files
-- and sets up the policies so authenticated users can upload and read their own.
-- ============================================================================

insert into storage.buckets (id, name, public)
values ('evidence', 'evidence', false)
on conflict (id) do nothing;



-- Policy to allow authenticated users to upload files to 'evidence' bucket
do $$ begin drop policy if exists "Allow authenticated uploads" on storage.objects; end $$;
create policy "Allow authenticated uploads"
on storage.objects for insert
to authenticated
with check ( bucket_id = 'evidence' );

-- Policy to allow users to read their own evidence files
do $$ begin drop policy if exists "Allow user to read own evidence" on storage.objects; end $$;
create policy "Allow user to read own evidence"
on storage.objects for select
to authenticated
using ( bucket_id = 'evidence' );

-- Policy to allow users to delete their own evidence files
do $$ begin drop policy if exists "Allow user to delete own evidence" on storage.objects; end $$;
create policy "Allow user to delete own evidence"
on storage.objects for delete
to authenticated
using ( bucket_id = 'evidence' );
