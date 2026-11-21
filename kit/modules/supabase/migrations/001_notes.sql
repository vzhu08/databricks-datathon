-- Coordinate migration ordering with the project steward. Policies never trust client owner_id alone.
create table if not exists public.kit_notes (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  title text not null check (char_length(title) between 1 and 200),
  body text not null default '' check (char_length(body) <= 50000),
  created_at timestamptz not null default now()
);
create index if not exists kit_notes_owner_idx on public.kit_notes(owner_id);
alter table public.kit_notes enable row level security;
create policy kit_notes_select on public.kit_notes for select to authenticated using ((select auth.uid()) = owner_id);
create policy kit_notes_insert on public.kit_notes for insert to authenticated with check ((select auth.uid()) = owner_id);
create policy kit_notes_update on public.kit_notes for update to authenticated using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy kit_notes_delete on public.kit_notes for delete to authenticated using ((select auth.uid()) = owner_id);
grant select, insert, update, delete on public.kit_notes to authenticated;
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types) values ('kit-private','kit-private',false,5000000,array['text/plain','application/pdf','image/png','image/jpeg']) on conflict(id) do nothing;
create policy kit_files_select on storage.objects for select to authenticated using (bucket_id='kit-private' and (storage.foldername(name))[1]=(select auth.uid())::text);
create policy kit_files_insert on storage.objects for insert to authenticated with check (bucket_id='kit-private' and (storage.foldername(name))[1]=(select auth.uid())::text);
create policy kit_files_delete on storage.objects for delete to authenticated using (bucket_id='kit-private' and (storage.foldername(name))[1]=(select auth.uid())::text);
