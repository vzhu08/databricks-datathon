import { z } from 'zod';
import type { SupabaseClient } from '@supabase/supabase-js';
import { httpJson, KitError } from '../../../packages/runtime/src/index';
import {
  type Chunk,
  ChunkSchema,
  type Embedder,
  type EmbeddingModel,
  validateVector,
} from './index';
export function openAIEmbedder(options: {
  apiKey: string;
  model: string;
  dimensions: number;
  fetcher?: typeof fetch;
}): Embedder {
  const identity = { provider: 'openai', model: options.model, dimensions: options.dimensions };
  return {
    identity,
    async embed(texts, signal) {
      if (!texts.length) return [];
      const response = await httpJson(
        'https://api.openai.com/v1/embeddings',
        z.object({
          data: z.array(z.object({ index: z.number().int(), embedding: z.array(z.number()) })),
        }),
        {
          method: 'POST',
          headers: {
            authorization: `Bearer ${options.apiKey}`,
            'content-type': 'application/json',
          },
          body: JSON.stringify({
            model: options.model,
            dimensions: options.dimensions,
            input: texts,
          }),
          signal,
          fetcher: options.fetcher,
        },
      );
      const sorted = response.data.sort((a, b) => a.index - b.index);
      if (sorted.length !== texts.length || sorted.some((v, n) => v.index !== n))
        throw new KitError('INVALID_EMBEDDINGS', 'Invalid embedding indexes', 502);
      return sorted.map((v) => validateVector(v.embedding, identity));
    },
  };
}
/** Client must carry the signed-in user's JWT. Never use a service role for tenant queries. */
export class SupabaseVectorIndex {
  constructor(
    private client: SupabaseClient,
    readonly identity: EmbeddingModel,
  ) {
    if (identity.dimensions !== 1536) throw new Error('Migration expects 1536 dimensions');
  }
  async replaceDocument(userId: string, documentId: string, chunks: Chunk[], embedder: Embedder) {
    if (
      embedder.identity.provider !== this.identity.provider ||
      embedder.identity.model !== this.identity.model ||
      embedder.identity.dimensions !== this.identity.dimensions
    )
      throw new Error('Embedding model incompatible');
    if (chunks.some((c) => c.documentId !== documentId)) throw new Error('Document mismatch');
    const vectors = chunks.length ? await embedder.embed(chunks.map((c) => c.text)) : [];
    if (vectors.length !== chunks.length) throw new Error('Embedding count mismatch');
    const rows = chunks.map((chunk, n) => ({
      id: chunk.id,
      user_id: userId,
      document_id: documentId,
      content: ChunkSchema.parse(chunk),
      embedding: validateVector(vectors[n]!, this.identity),
      model: `${this.identity.provider}/${this.identity.model}`,
      dimensions: this.identity.dimensions,
    }));
    const { error } = await this.client.rpc('kit_replace_chunks', {
      p_document_id: documentId,
      p_rows: rows,
    });
    if (error) throw new Error(error.message);
  }
  async search(
    vector: number[],
    options: { limit?: number; filters?: Record<string, unknown>; minScore?: number } = {},
  ) {
    const { data, error } = await this.client.rpc('kit_match_chunks', {
      query_embedding: validateVector(vector, this.identity),
      expected_model: `${this.identity.provider}/${this.identity.model}`,
      match_count: z
        .number()
        .int()
        .min(1)
        .max(100)
        .parse(options.limit ?? 5),
      min_score: options.minScore ?? 0.2,
      metadata_filter: options.filters ?? {},
    });
    if (error) throw new Error(error.message);
    return z
      .array(z.object({ content: ChunkSchema, score: z.number() }))
      .parse(data)
      .map((r) => ({
        chunk: r.content,
        score: r.score,
        method: 'vector' as const,
        citation: {
          documentId: r.content.documentId,
          segmentId: r.content.segmentId,
          start: r.content.start,
          end: r.content.end,
          quote: r.content.text,
        },
      }));
  }
}
