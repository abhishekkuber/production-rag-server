alter table if exists public.document_chunks
alter column embedding set data type vector(1024);