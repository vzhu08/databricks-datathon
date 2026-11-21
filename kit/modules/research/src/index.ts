import { z } from 'zod';
export const SearchHitSchema = z.object({
  title: z.string(),
  url: z.url(),
  originalURL: z.url().optional(),
  snippet: z.string().default(''),
  publishedAt: z.string().optional(),
});
export type SearchHit = z.infer<typeof SearchHitSchema>;
export type SearchProvider = {
  name: string;
  mode: 'fixture' | 'live';
  search: (
    query: string,
    options?: { limit?: number; signal?: AbortSignal },
  ) => Promise<SearchHit[]>;
};
export function normalizeURL(input: string): string {
  const url = new URL(input);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password)
    throw new Error('Only credential-free HTTP(S) URLs are allowed');
  if (url.port && !['80', '443'].includes(url.port)) throw new Error('Nonstandard port rejected');
  url.hash = '';
  for (const key of [...url.searchParams.keys()])
    if (/^utm_|^(fbclid|gclid)$/i.test(key)) url.searchParams.delete(key);
  url.searchParams.sort();
  return url.href;
}
export function deduplicateResults(results: SearchHit[]): SearchHit[] {
  const seen = new Set<string>();
  const unique: SearchHit[] = [];
  for (const raw of results) {
    const hit = SearchHitSchema.parse(raw);
    try {
      const url = normalizeURL(hit.url);
      const originalURL = hit.originalURL ?? hit.url;
      if (normalizeURL(originalURL) !== url) throw new Error('Original URL does not match source');
      if (!seen.has(url)) {
        seen.add(url);
        unique.push({ ...hit, url, originalURL });
      }
    } catch {
      /* Reject unsupported provider URLs. */
    }
  }
  return unique;
}
export function fixtureSearchProvider(hits: SearchHit[]): SearchProvider {
  const fixture = z.array(SearchHitSchema).parse(hits);
  return {
    name: 'synthetic-fixture',
    mode: 'fixture',
    async search(query, options) {
      const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
      if (!terms.length) return [];
      return deduplicateResults(fixture)
        .filter((hit) =>
          terms.some((term) => `${hit.title} ${hit.snippet}`.toLowerCase().includes(term)),
        )
        .slice(0, options?.limit ?? 5);
    },
  };
}
