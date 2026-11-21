import { describe, it, expect } from 'vitest';
import {
  LocalIndex,
  chunkDocument,
  answerFromResults,
  evaluateRetrieval,
  type Embedder,
} from '../src/index';
import { openAIEmbedder, SupabaseVectorIndex } from '../src/server';
import type { SupabaseClient } from '@supabase/supabase-js';
import { normalizeText } from '../../documents/src/index';
import corpus from '../fixtures/corpus.json';
import cases from '../fixtures/evaluation.json';
const fixtureEmbedder: Embedder = {
  identity: { provider: 'fixture', model: 'keywords-v1', dimensions: 2 },
  embed: async (texts) => texts.map((t) => (/garden/i.test(t) ? [1, 0] : [0, 1])),
};
function index() {
  const i = new LocalIndex();
  corpus.forEach((d) => i.upsert(normalizeText(d)));
  return i;
}
describe('retrieval', () => {
  it('finds real evidence, filters and scores evaluation', () => {
    const i = index();
    expect(i.search('vegetables')[0]!.chunk.documentId).toBe('garden');
    expect(i.search('vegetables', { filters: { filename: 'transit.md' } })).toHaveLength(0);
    expect(evaluateRetrieval(i, cases)).toMatchObject({
      recallAtK: 1,
      meanReciprocalRank: 1,
      citationValidity: 1,
    });
    expect(
      answerFromResults('vegetables', i.search('vegetables'), i.getDocuments()).citations,
    ).toHaveLength(1);
  });
  it('handles empty query and irrelevant evidence', () => {
    const i = index();
    expect(i.search('')).toEqual([]);
    expect(answerFromResults('spacecraft', i.search('spacecraft'), i.getDocuments()).status).toBe(
      'no-evidence',
    );
  });
  it('chunks without breaking UTF-16 surrogate pairs and retains exact spans', () => {
    const d = normalizeText({ filename: 'emoji.txt', text: '🌿'.repeat(40) });
    const chunks = chunkDocument(d, { maxChars: 17, overlap: 3 });
    expect(chunks.length).toBeGreaterThan(1);
    for (const c of chunks) {
      expect(c.text).toBe(d.text.slice(c.start, c.end));
      expect(c.start % 2).toBe(0);
      expect(c.end % 2).toBe(0);
    }
  });
  it('updates changed sources and deletes stale vectors', async () => {
    const i = index();
    expect(i.upsert(normalizeText(corpus[0]!)).changed).toBe(false);
    await i.embed(fixtureEmbedder);
    expect((await i.searchVector('garden', fixtureEmbedder))[0]!.chunk.documentId).toBe('garden');
    i.upsert(normalizeText({ ...corpus[0]!, text: 'The amended source is about bees.' }));
    expect(i.search('vegetables')).toEqual([]);
    expect(await i.searchVector('garden', fixtureEmbedder)).toEqual([]);
  });
  it('rejects model and dimension mismatches', async () => {
    const i = index();
    await i.embed(fixtureEmbedder);
    await expect(
      i.searchVector('garden', {
        ...fixtureEmbedder,
        identity: { ...fixtureEmbedder.identity, model: 'v2' },
      }),
    ).rejects.toThrow('incompatible');
    await expect(new LocalIndex().searchVector('x', fixtureEmbedder)).rejects.toThrow();
  });
  it('real embeddings adapter validates, sorts and passes configured model', async () => {
    const e = openAIEmbedder({
      apiKey: 'fixture-not-a-key',
      model: 'test-model',
      dimensions: 2,
      fetcher: async (_url, init) => {
        expect(JSON.parse(String(init?.body)).model).toBe('test-model');
        return Response.json({
          data: [
            { index: 1, embedding: [0, 1] },
            { index: 0, embedding: [1, 0] },
          ],
        });
      },
    });
    expect(await e.embed(['a', 'b'])).toEqual([
      [1, 0],
      [0, 1],
    ]);
  });
  it('passes owner/document/model scope to Supabase RPC and validates results', async () => {
    const calls: { name: string; args: Record<string, unknown> }[] = [];
    const document = normalizeText(corpus[0]!);
    const chunks = chunkDocument(document);
    const client = {
      rpc: async (name: string, args: Record<string, unknown>) => {
        calls.push({ name, args });
        return {
          data: name === 'kit_match_chunks' ? [{ content: chunks[0], score: 0.9 }] : null,
          error: null,
        };
      },
    } as unknown as SupabaseClient;
    const identity = { provider: 'fixture', model: 'large-v1', dimensions: 1536 };
    const index = new SupabaseVectorIndex(client, identity);
    const embedder = {
      identity,
      embed: async (texts: string[]) =>
        texts.map(() => Array.from({ length: 1536 }, (_, i) => (i === 0 ? 1 : 0))),
    };
    await index.replaceDocument('signed-in-user', document.id, chunks, embedder);
    expect(calls[0]!.name).toBe('kit_replace_chunks');
    expect(calls[0]!.args.p_document_id).toBe(document.id);
    const results = await index.search((await embedder.embed(['query']))[0]!, {
      filters: { filename: document.filename },
    });
    expect(calls[1]!.args.expected_model).toBe('fixture/large-v1');
    expect(calls[1]!.args.metadata_filter).toEqual({ filename: document.filename });
    expect(results[0]!.citation.quote).toBe(chunks[0]!.text);
    await expect(index.replaceDocument('user', 'wrong-document', chunks, embedder)).rejects.toThrow(
      'Document mismatch',
    );
  });
  it('requires source documents instead of marking unverified citations supported', () => {
    const i = index();
    const hits = i.search('vegetables');
    expect(() => Reflect.apply(answerFromResults, undefined, ['vegetables', hits])).toThrow(
      'Verified source documents are required',
    );
    expect(answerFromResults('vegetables', hits, []).status).toBe('no-evidence');
    expect(answerFromResults('vegetables', hits, i.getDocuments()).status).toBe('supported');
  });
  it('rejects stale hashes and citations that do not identify the retrieved passage', () => {
    const i = index();
    const hits = i.search('vegetables');
    const stale = structuredClone(hits);
    stale[0]!.chunk.documentHash = 'previous-revision';
    expect(answerFromResults('vegetables', stale, i.getDocuments()).status).toBe('no-evidence');
    const detached = structuredClone(hits);
    detached[0]!.chunk.text = 'An unrelated retrieved passage';
    expect(answerFromResults('vegetables', detached, i.getDocuments()).status).toBe('no-evidence');
    const forged = structuredClone(hits);
    forged[0]!.citation.quote = 'Invented evidence';
    expect(answerFromResults('vegetables', forged, i.getDocuments()).citations).toHaveLength(0);
  });
  it('returns no evidence for function words and unrelated natural-language questions', () => {
    const i = new LocalIndex();
    i.upsert(
      normalizeText({
        filename: 'garden.txt',
        text: 'The garden is green.\nThis is a community project.',
      }),
    );
    for (const query of ['what is the', 'What is the spacecraft color?'])
      expect(answerFromResults(query, i.search(query), i.getDocuments()).status).toBe(
        'no-evidence',
      );
    expect(i.search('What is the garden?')[0]!.chunk.text).toContain('garden');
  });
  it('supports domain stopword overrides and explicit lexical term coverage', () => {
    const i = index();
    expect(i.search('gardens spacecraft', { minTermCoverage: 1 })).toHaveLength(0);
    expect(i.search('gardens spacecraft', { minTermCoverage: 0.5 })[0]!.chunk.documentId).toBe(
      'garden',
    );
    expect(() => i.search('gardens', { minTermCoverage: 2 })).toThrow();
    const domain = new LocalIndex({ stopwords: [] });
    domain.upsert(normalizeText({ filename: 'word.txt', text: 'The' }));
    expect(domain.search('the')).toHaveLength(1);
  });
  it('searches many short passages without a quadratic corpus scan', () => {
    const i = new LocalIndex();
    i.upsert(
      normalizeText({
        filename: 'large.txt',
        text: Array.from({ length: 20_000 }, (_, n) => `Garden irrigation record ${n}`).join('\n'),
      }),
    );
    const start = performance.now();
    const hits = i.search('garden irrigation');
    expect(hits).toHaveLength(5);
    // Broad regression budget: the previous per-passage DF scan takes several seconds here.
    expect(performance.now() - start).toBeLessThan(2000);
    expect(hits.every((hit) => hit.score === hits[0]!.score)).toBe(true);
  });
});
