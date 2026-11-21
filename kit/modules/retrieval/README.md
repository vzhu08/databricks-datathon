# Search and retrieval

## 1. What problem does this solve, and when should I use it?

Search a small evidence corpus with deterministic lexical ranking, or add real embeddings and Supabase persistence. Every hit carries an exact source citation. Use lexical mode to develop without credentials or paid calls.

## 2. What is the smallest working example?

```sh
node --import tsx modules/retrieval/examples/demo.ts
```

```ts
const index = new LocalIndex();
index.upsert(document);
const hits = index.search('community gardens');
const answer = answerFromResults('community gardens', hits, index.getDocuments());
```

Import these browser-safe helpers from `modules/retrieval/src/index.ts`.

## 3. How do I add it to a fresh project or an existing project?

Select `retrieval`; its dependency is `documents`. Keep OpenAI/Supabase adapters in server routes. The local index requires no database. Existing projects can construct an instance per user/workbench; do not share a private index globally across tenants.

## 4. What does the API accept and return?

`chunkDocument(document,{maxChars=800,overlap=100})` produces stable source/range/content IDs and hashes without splitting surrogate pairs. `LocalIndex.upsert` returns `{changed,chunks}` and invalidates vectors when source hash changes; `remove` deletes source/chunks/vectors. `search(query,{limit,filters,minScore,minTermCoverage})` returns `{chunk,score,citation,method}` ranked by a BM25-style lexical score. A configurable English stopword list removes question/function words from the query; all-stopword queries and queries with no remaining word matches return no evidence. `minTermCoverage` (0–1) can require a chosen fraction of significant query words; every hit requires at least one such match even at the default 0. Pass `stopwords: []` to the constructor when exact domain terms require those words. Token frequencies and query document frequencies are computed in one corpus scan. Exact metadata filters include filename/page/row/section. `embed(embedder)` batches up to 32 chunks; `searchVector` checks provider/model/dimensions and uses cosine similarity. `openAIEmbedder({apiKey,model,dimensions})` calls the real embeddings API. `answerFromResults(query,results,documents)` requires the verified source documents and returns supported extractive quotations or explicit no-evidence. It checks source hash, citation validity and exact agreement with the retrieved chunk; omitted sources throw instead of marking unchecked text supported. It never invents a generative answer. `evaluateRetrieval` reports recall@k, reciprocal rank and citation validity.

## 5. What prerequisites, environment variables, or credentials are needed?

Local: Node and declared packages only. Live embeddings: server-only OPENAI_API_KEY, configured OPENAI_EMBEDDING_MODEL and dimensions. Select a model supporting requested dimensions; no default model/cost assumptions. Supabase: authenticated client, SQL migration, and embedding dimension 1536. A service-role key must not be used for tenant retrieval.

## 6. What changes must I make to routes, schema, storage, or UI?

Apply `migrations/020_retrieval.sql` through migration stewardship if using Supabase. It creates kit_document_chunks with owner RLS, atomic document replacement and model-aware retrieval RPCs. Bind the client to a signed-in user's JWT. `SupabaseVectorIndex.replaceDocument(userId,documentId,chunks,embedder)` replaces a document transactionally; search filters on the full stored chunk metadata. The local UI should display citation labels and highlight spans with the original normalized document. Persist embedding identity with corpus snapshots; re-embed into a new index after changing model/dimensions. No browser key is required.

## 7. How do I verify it and handle expected failures?

```sh
npx vitest run modules/retrieval/tests
node --import tsx modules/retrieval/examples/demo.ts
```

The synthetic evaluation corpus has three topics and expected source IDs. Tests measure exact citation validity, empty/no-hit behavior, filters, UTF-16 boundaries, updates/stale vector removal, adapter requests and incompatible model failures. Do not treat this tiny dataset as production quality evidence. API failures remain errors; there is no silent fixture fallback. Handle embedding quotas and upstream failures explicitly; batching/retry policy is caller controlled.

Implementation: implemented. Local: tests passed 2026-10-09. Exported project: passed 2026-10-09 in the standalone full recipe (clean install, types, module tests, build and local HTTP). Live OpenAI and Supabase migration/RLS integration: not run — require operator credentials and authorization. Source revision: base 0fcd52a plus implementation commit.

## 8. What does it depend on, and what are its limits?

Depends on documents, Zod/shared contracts/runtime and Supabase JS. Local defaults cap documents at 100; scoring scans corpus tokens once per query plus matching term counts and result sorting; it is intended for hackathon-scale corpora. Lexical matching is exact, case-insensitive word overlap, not semantic question answering: it does not infer synonyms, stem plurals, assess claim relevance, or handle all languages with its English stopwords. A valid citation proves the returned text exists, not that it fully answers the question. Segment-preserving chunks do not join short paragraphs, so tune source segmentation for real retrieval. Supabase migration uses exact vector scans; add a measured HNSW index when corpus size justifies it. Hybrid fusion/reranking are optional application enhancements; normalize score scales and re-evaluate before combining lexical and vector hits. Embedding calls may incur provider usage; no pricing table is assumed.

Original code/fixtures: MIT. [Supabase vectors](https://supabase.com/docs/guides/ai/vector-columns), [OpenAI embeddings](https://platform.openai.com/docs/guides/embeddings). Official APIs and installed packages inspected 2026-10-09.
