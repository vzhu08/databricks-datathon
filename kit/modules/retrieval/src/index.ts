import { z } from 'zod';
import { contentHash } from '../../documents/src/index';
import {
  validateDocument,
  validateCitation,
  type Citation,
  type NormalizedDocument,
} from '../../../packages/contracts/src/index';

export const ChunkSchema = z.object({
  id: z.string(),
  documentId: z.string(),
  documentHash: z.string(),
  hash: z.string(),
  text: z.string(),
  start: z.number().int(),
  end: z.number().int(),
  segmentId: z.string(),
  metadata: z.record(z.string(), z.unknown()),
});
export type Chunk = z.infer<typeof ChunkSchema>;
export type SearchResult = {
  chunk: Chunk;
  score: number;
  citation: Citation;
  method: 'lexical' | 'vector';
};
export type EmbeddingModel = { provider: string; model: string; dimensions: number };
export type Embedder = {
  identity: EmbeddingModel;
  embed: (texts: string[], signal?: AbortSignal) => Promise<number[][]>;
};
export function chunkDocument(
  input: NormalizedDocument,
  options: { maxChars?: number; overlap?: number } = {},
): Chunk[] {
  const document = validateDocument(input),
    { maxChars = 800, overlap = 100 } = options;
  if (
    !Number.isInteger(maxChars) ||
    maxChars < 16 ||
    !Number.isInteger(overlap) ||
    overlap < 0 ||
    overlap >= maxChars
  )
    throw new Error('Chunk bounds require 0 <= overlap < maxChars and maxChars >= 16');
  const chunks: Chunk[] = [];
  for (const segment of document.segments) {
    for (let start = segment.start; start < segment.end;) {
      let end = Math.min(start + maxChars, segment.end);
      if (end < segment.end && /[\uDC00-\uDFFF]/.test(document.text[end]!)) end--;
      const text = document.text.slice(start, end),
        hash = contentHash(text);
      if (text.trim())
        chunks.push({
          id: `${document.id}:${segment.id}:${start}:${hash}`,
          documentId: document.id,
          documentHash: document.hash,
          hash,
          text,
          start,
          end,
          segmentId: segment.id,
          metadata: {
            ...document.metadata,
            filename: document.filename,
            page: segment.page,
            row: segment.row,
            section: segment.section,
          },
        });
      if (end === segment.end) break;
      start = Math.max(start + 1, end - overlap);
      if (/[\uDC00-\uDFFF]/.test(document.text[start]!)) start++;
    }
  }
  return chunks;
}
/** English question/function words only. Domain applications can override this list. */
export const DEFAULT_QUERY_STOPWORDS: readonly string[] =
  'a an and are as at be been being but by can could did do does for from had has have how i if in into is it its may might of on or our please should than that the their them then there these they this those to us was we were what when where which who why will with would you your'.split(
    ' ',
  );
function tokens(s: string): string[] {
  return s.toLocaleLowerCase('en-US').match(/[\p{L}\p{N}]+/gu) ?? [];
}
function citation(chunk: Chunk): Citation {
  return {
    documentId: chunk.documentId,
    segmentId: chunk.segmentId,
    start: chunk.start,
    end: chunk.end,
    quote: chunk.text,
    label: `${chunk.metadata.filename}${chunk.metadata.page ? ` · page ${chunk.metadata.page}` : ''}`,
  };
}
function matches(chunk: Chunk, filters: Record<string, unknown> = {}) {
  return Object.entries(filters).every(([key, value]) => chunk.metadata[key] === value);
}
function sameModel(a: EmbeddingModel | undefined, b: EmbeddingModel) {
  return a?.provider === b.provider && a.model === b.model && a.dimensions === b.dimensions;
}
function limitValue(limit = 5) {
  return z.number().int().min(1).max(100).parse(limit);
}
export function validateVector(vector: number[], identity: EmbeddingModel): number[] {
  if (
    !Number.isInteger(identity.dimensions) ||
    identity.dimensions < 1 ||
    !identity.model ||
    !identity.provider ||
    vector.length !== identity.dimensions ||
    vector.some((v) => !Number.isFinite(v))
  )
    throw new Error('Embedding model/dimension mismatch');
  return vector;
}
export function cosineSimilarity(a: number[], b: number[]): number {
  if (
    a.length !== b.length ||
    a.some((v) => !Number.isFinite(v)) ||
    b.some((v) => !Number.isFinite(v))
  )
    throw new Error('Invalid vectors');
  let dot = 0,
    aa = 0,
    bb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i]! * b[i]!;
    aa += a[i]! ** 2;
    bb += b[i]! ** 2;
  }
  return aa && bb ? dot / Math.sqrt(aa * bb) : 0;
}
export class LocalIndex {
  private docs = new Map<string, NormalizedDocument>();
  private chunks = new Map<string, Chunk[]>();
  private vectors = new Map<string, number[]>();
  private model?: EmbeddingModel;
  constructor(
    private options: {
      maxDocuments?: number;
      maxChars?: number;
      overlap?: number;
      stopwords?: readonly string[];
    } = {},
  ) {}
  upsert(input: NormalizedDocument): { changed: boolean; chunks: number } {
    const document = validateDocument(input);
    const previous = this.docs.get(document.id);
    if (
      previous?.hash === document.hash &&
      previous.text === document.text &&
      previous.filename === document.filename &&
      JSON.stringify(previous.metadata) === JSON.stringify(document.metadata) &&
      JSON.stringify(previous.segments) === JSON.stringify(document.segments)
    )
      return { changed: false, chunks: this.chunks.get(document.id)!.length };
    if (!this.docs.has(document.id) && this.docs.size >= (this.options.maxDocuments ?? 100))
      throw new Error('Local corpus limit reached');
    this.remove(document.id);
    const chunks = chunkDocument(document, this.options);
    this.docs.set(document.id, document);
    this.chunks.set(document.id, chunks);
    return { changed: true, chunks: chunks.length };
  }
  remove(id: string) {
    for (const c of this.chunks.get(id) ?? []) this.vectors.delete(c.id);
    this.chunks.delete(id);
    this.docs.delete(id);
  }
  getDocuments() {
    return [...this.docs.values()];
  }
  search(
    query: string,
    options: {
      limit?: number;
      filters?: Record<string, unknown>;
      minScore?: number;
      minTermCoverage?: number;
    } = {},
  ): SearchResult[] {
    const limit = limitValue(options.limit);
    const stopwords = new Set(
      (this.options.stopwords ?? DEFAULT_QUERY_STOPWORDS).map((word) =>
        word.toLocaleLowerCase('en-US'),
      ),
    );
    const terms = [
      ...new Set(tokens(z.string().max(10000).parse(query)).filter((term) => !stopwords.has(term))),
    ];
    const minTermCoverage = z
      .number()
      .min(0)
      .max(1)
      .parse(options.minTermCoverage ?? 0);
    if (!terms.length) return [];
    const termSet = new Set(terms);
    const documentFrequency = new Map(terms.map((term) => [term, 0]));
    const corpus = [...this.chunks.values()]
      .flat()
      .filter((chunk) => matches(chunk, options.filters));
    // One token scan per passage; each query term contributes to DF at most once.
    const indexed = corpus.map((chunk) => {
      const words = tokens(chunk.text),
        frequencies = new Map<string, number>();
      for (const word of words)
        if (termSet.has(word)) frequencies.set(word, (frequencies.get(word) ?? 0) + 1);
      for (const term of frequencies.keys())
        documentFrequency.set(term, documentFrequency.get(term)! + 1);
      return { chunk, length: words.length, frequencies };
    });
    const mean =
      indexed.reduce((total, entry) => total + entry.length, 0) / Math.max(1, indexed.length);
    const idf = new Map(
      terms.map((term) => {
        const df = documentFrequency.get(term)!;
        return [term, Math.log(1 + (indexed.length - df + 0.5) / (df + 0.5))];
      }),
    );
    return indexed
      .filter(
        (entry) =>
          entry.frequencies.size > 0 && entry.frequencies.size / terms.length >= minTermCoverage,
      )
      .map(({ chunk, length, frequencies }) => {
        let score = 0;
        for (const [term, tf] of frequencies)
          score +=
            (idf.get(term)! * (tf * 2.2)) / (tf + 1.2 * (0.25 + (0.75 * length) / (mean || 1)));
        return { chunk, score, citation: citation(chunk), method: 'lexical' as const };
      })
      .filter((result) => result.score > (options.minScore ?? 0))
      .sort((a, b) => b.score - a.score || a.chunk.id.localeCompare(b.chunk.id))
      .slice(0, limit);
  }

  async embed(embedder: Embedder, signal?: AbortSignal): Promise<number> {
    if (this.model && !sameModel(this.model, embedder.identity))
      throw new Error('Embedding model incompatible; create a new index');
    this.model = { ...embedder.identity };
    const chunks = [...this.chunks.values()].flat().filter((c) => !this.vectors.has(c.id));
    for (let i = 0; i < chunks.length; i += 32) {
      signal?.throwIfAborted();
      const batch = chunks.slice(i, i + 32),
        vectors = await embedder.embed(
          batch.map((c) => c.text),
          signal,
        );
      if (vectors.length !== batch.length) throw new Error('Embedding result count mismatch');
      vectors.forEach((v) => validateVector(v, embedder.identity));
      vectors.forEach((v, n) => this.vectors.set(batch[n]!.id, v));
    }
    return chunks.length;
  }
  async searchVector(
    query: string,
    embedder: Embedder,
    options: {
      limit?: number;
      filters?: Record<string, unknown>;
      minScore?: number;
      signal?: AbortSignal;
    } = {},
  ): Promise<SearchResult[]> {
    const limit = limitValue(options.limit);
    if (!query.trim()) return [];
    if (!sameModel(this.model, embedder.identity))
      throw new Error('Query embedding model incompatible');
    const [queryVector] = await embedder.embed([query], options.signal);
    validateVector(queryVector!, embedder.identity);
    return [...this.chunks.values()]
      .flat()
      .filter((c) => this.vectors.has(c.id) && matches(c, options.filters))
      .map((chunk) => ({
        chunk,
        score: cosineSimilarity(queryVector!, this.vectors.get(chunk.id)!),
        citation: citation(chunk),
        method: 'vector' as const,
      }))
      .filter((r) => r.score > (options.minScore ?? 0.2))
      .sort((a, b) => b.score - a.score || a.chunk.id.localeCompare(b.chunk.id))
      .slice(0, limit);
  }
}
/** Extractive answer only: returned sentences are the retrieved evidence itself. */
export function answerFromResults(
  query: string,
  results: SearchResult[],
  documents: NormalizedDocument[],
) {
  if (!Array.isArray(documents)) throw new Error('Verified source documents are required');
  const verifiedDocuments = documents.map(validateDocument);
  const valid = results.filter((result) => {
    const parsed = ChunkSchema.safeParse(result.chunk);
    if (!parsed.success || !validateCitation(result.citation, verifiedDocuments)) return false;
    const chunk = parsed.data,
      source = verifiedDocuments.find((document) => document.id === chunk.documentId);
    return (
      source?.hash === chunk.documentHash &&
      result.citation.documentId === chunk.documentId &&
      result.citation.segmentId === chunk.segmentId &&
      result.citation.start === chunk.start &&
      result.citation.end === chunk.end &&
      result.citation.quote === chunk.text
    );
  });
  return {
    query,
    answer: valid.length
      ? valid.map((r, i) => `[${i + 1}] ${r.citation.quote.trim()}`).join('\n\n')
      : 'No relevant evidence found.',
    citations: valid.map((r) => r.citation),
    status: valid.length ? ('supported' as const) : ('no-evidence' as const),
    mode: 'local' as const,
  };
}
export function evaluateRetrieval(
  index: LocalIndex,
  cases: { query: string; expectedDocumentId: string }[],
  k = 3,
) {
  let hits = 0,
    reciprocal = 0,
    citations = 0,
    valid = 0;
  for (const test of cases) {
    const results = index.search(test.query, { limit: k });
    const rank = results.findIndex((r) => r.chunk.documentId === test.expectedDocumentId);
    if (rank >= 0) {
      hits++;
      reciprocal += 1 / (rank + 1);
    }
    for (const r of results) {
      citations++;
      if (validateCitation(r.citation, index.getDocuments())) valid++;
    }
  }
  return {
    cases: cases.length,
    recallAtK: cases.length ? hits / cases.length : 0,
    meanReciprocalRank: cases.length ? reciprocal / cases.length : 0,
    citationValidity: citations ? valid / citations : 1,
    k,
  };
}
