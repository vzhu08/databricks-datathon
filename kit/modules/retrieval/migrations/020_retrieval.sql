-- Apply to a Supabase project after auth is available; distinct module-owned names.
create extension if not exists vector with schema extensions;
create table public.kit_document_chunks (
  id text not null, user_id uuid not null references auth.users(id) on delete cascade,
  document_id text not null, content jsonb not null, embedding extensions.vector(1536) not null,
  model text not null, dimensions integer not null check (dimensions = 1536),
  primary key (user_id, id)
);
alter table public.kit_document_chunks enable row level security;
revoke all on public.kit_document_chunks from public, anon;
grant select, insert, update, delete on public.kit_document_chunks to authenticated;
create policy kit_chunks_owner on public.kit_document_chunks for all to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create index kit_chunks_owner_document on public.kit_document_chunks(user_id, document_id);
create or replace function public.kit_replace_chunks(p_document_id text, p_rows jsonb)
returns void language plpgsql security invoker set search_path = public, extensions as $$
begin
  if auth.uid() is null then raise exception 'Authentication required'; end if;
  if jsonb_array_length(p_rows) > 1000 then raise exception 'Chunk limit exceeded'; end if;
  delete from public.kit_document_chunks where user_id = auth.uid() and document_id = p_document_id;
  insert into public.kit_document_chunks(id,user_id,document_id,content,embedding,model,dimensions)
  select x.id, auth.uid(), p_document_id, x.content, x.embedding::extensions.vector(1536), x.model, x.dimensions
  from jsonb_to_recordset(p_rows) x(id text,content jsonb,embedding text,model text,dimensions integer);
end $$;
create or replace function public.kit_match_chunks(query_embedding extensions.vector(1536),expected_model text,match_count integer default 5,min_score double precision default 0.2,metadata_filter jsonb default '{}')
returns table(content jsonb,score double precision) language sql stable security invoker set search_path=public,extensions as $$
  select c.content, 1-(c.embedding <=> query_embedding) score from public.kit_document_chunks c
  where c.user_id = (select auth.uid()) and c.model=expected_model and c.content->'metadata' @> metadata_filter
  and 1-(c.embedding <=> query_embedding) > min_score
  order by c.embedding <=> query_embedding,c.id limit greatest(1,least(match_count,100));
$$;
revoke all on function public.kit_replace_chunks(text,jsonb) from public,anon;
revoke all on function public.kit_match_chunks(extensions.vector,text,integer,double precision,jsonb) from public,anon;
grant execute on function public.kit_replace_chunks(text,jsonb) to authenticated;
grant execute on function public.kit_match_chunks(extensions.vector,text,integer,double precision,jsonb) to authenticated;
