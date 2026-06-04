# Database — Supabase setup

Nyaya AI uses Supabase (managed Postgres + Auth + RLS) as the system of
record. This folder ships the schema as version-controlled migrations.

## One-time setup

1. Create a Supabase project at <https://supabase.com>.
2. From **Project settings → API**, copy these into your root `.env`:
   ```
   SUPABASE_URL=https://<ref>.supabase.co
   SUPABASE_ANON_KEY=<anon key>
   SUPABASE_SERVICE_KEY=<service role key>      # backend only — never in the browser
   SUPABASE_JWT_SECRET=<JWT secret>             # for backend JWT verification
   ```
3. Apply the schema:
   - Open **Supabase Studio → SQL Editor**.
   - Paste the entire contents of [`migrations/001_init.sql`](migrations/001_init.sql).
   - Click **Run**.
4. (Optional) Seed the eval test set from the JSON file:
   ```sql
   -- run inside Supabase SQL editor; replace the JSON literal with the contents
   -- of backend/eval/test_cases.json's `cases` array
   insert into test_cases (query, expected_sections)
   select c->>'query', array(select jsonb_array_elements_text(c->'expected_sections'))
   from jsonb_array_elements('[ ...paste cases array here... ]'::jsonb) as c;
   ```

## What the migration does

- Creates `profiles`, `chat_history`, `fir_records`, `investigations`,
  `cases`, `test_cases`, `eval_runs` with FKs and indexes.
- Enables **Row-Level Security** on every table.
- Adds `auth.uid() = user_id` policies so users can only ever see their own
  rows. `test_cases` and `eval_runs` are readable by any authenticated user;
  writes only via the backend's service-role key.
- Installs an `auth.users` insert trigger that auto-creates a matching
  `profiles` row on sign-up.

## Re-running

The script is **idempotent**: tables use `if not exists`, policies are
dropped + recreated inside `DO` blocks, trigger is dropped + recreated. Safe
to re-run any time.

## Future migrations

Add new files as `002_*.sql`, `003_*.sql`, etc., and apply them in order.
