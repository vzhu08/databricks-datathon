import { describe, it, expect } from 'vitest';
import { readFile } from 'node:fs/promises';
import { normalizeURL, deduplicateResults, fixtureSearchProvider } from '../src/index';
import {
  validateDestination,
  extractHTML,
  ResearchClient,
  tavilySearchProvider,
} from '../src/server';
import hits from '../fixtures/search.json';
const publicDNS = async () => [{ address: '93.184.216.34', family: 4 }];
describe('research', () => {
  it('normalizes and deduplicates with tracking removed', () => {
    expect(normalizeURL('https://example.org/a?b=2&utm_source=x&a=1#fragment')).toBe(
      'https://example.org/a?a=1&b=2',
    );
    expect(deduplicateResults(hits)).toHaveLength(1);
    expect(() => normalizeURL('file:///etc/passwd')).toThrow();
    expect(() => normalizeURL('https://user:password@example.org')).toThrow();
  });
  it('blocks SSRF private IPv4/IPv6, encoded IP, mixed DNS and ports', async () => {
    for (const url of [
      'http://127.0.0.1',
      'http://2130706433',
      'http://[::1]',
      'http://[::ffff:127.0.0.1]',
      'http://169.254.169.254',
      'http://10.0.0.2',
      'http://192.168.1.1',
      'http://localhost',
      'http://example.org:8080',
    ])
      await expect(validateDestination(url, publicDNS)).rejects.toThrow();
    await expect(
      validateDestination('https://example.org', async () => [
        { address: '93.184.216.34', family: 4 },
        { address: '127.0.0.1', family: 4 },
      ]),
    ).rejects.toThrow('mixed DNS');
    expect(
      (await validateDestination('https://example.org', publicDNS)).addresses[0]!.address,
    ).toBe('93.184.216.34');
  });
  it('extracts useful HTML and only actual publication dates', async () => {
    const html = await readFile(new URL('../fixtures/article.html', import.meta.url), 'utf8');
    const source = extractHTML(html, {
      originalURL: 'https://example.org/gardens',
      mode: 'fixture',
    });
    expect(source.text).toContain('Rainwater');
    expect(source.text).not.toContain('untrusted_code');
    expect(source.text).not.toContain('navigation');
    expect(source.publishedAt).toBe('2026-01-20T09:00:00Z');
    expect(
      extractHTML('<p>No date</p>', { originalURL: 'https://example.org' }).publishedAt,
    ).toBeUndefined();
  });
  it('keeps cache scoped and distinguishes fixture, cached and failures', async () => {
    let count = 0;
    const client = new ResearchClient(fixtureSearchProvider(hits), async (url) => {
      count++;
      return {
        html: '<article>Garden evidence</article>',
        finalURL: url,
        retrievedAt: '2026-01-01T00:00:00Z',
      };
    });
    expect((await client.research('garden', { scope: 'a' })).mode).toBe('fixture');
    expect((await client.research('garden', { scope: 'a' })).sources[0]!.cached).toBe(true);
    await client.research('garden', { scope: 'b' });
    expect(count).toBe(2);
    expect((await client.research('spaceflight', { scope: 'a' })).sources).toEqual([]);
    const failure = new ResearchClient(fixtureSearchProvider(hits), async () => {
      throw new Error('Timeout');
    });
    expect((await failure.research('garden', { scope: 'a' })).failures[0]!.message).toBe('Timeout');
  });
  it('uses real Tavily request shape and validates malformed responses', async () => {
    const provider = tavilySearchProvider('fixture-key', {
      fetcher: async (_url, init) => {
        expect(JSON.parse(String(init?.body))).toMatchObject({
          query: 'garden',
          max_results: 2,
          include_answer: false,
        });
        return Response.json({
          results: [{ title: 'Garden', url: 'https://example.org', content: 'Evidence' }],
        });
      },
    });
    expect(await provider.search('garden', { limit: 2 })).toHaveLength(1);
    expect(provider.mode).toBe('live');
    await expect(
      tavilySearchProvider('test', {
        fetcher: async () => Response.json({ invalid: true }),
      }).search('garden'),
    ).rejects.toThrow();
  });
  it('retains original provider URL through repeated deduplication and cached research', async () => {
    const originalURL = 'https://example.org/gardens?utm_source=original#planting';
    const hits = [{ title: 'Garden', url: originalURL, snippet: 'garden' }];
    const deduped = deduplicateResults(deduplicateResults(hits));
    expect(deduped[0]).toMatchObject({ url: 'https://example.org/gardens', originalURL });
    const client = new ResearchClient(fixtureSearchProvider(hits), async (url) => ({
      html: '<article>garden</article>',
      finalURL: url,
      retrievedAt: '2026-10-09T00:00:00Z',
    }));
    const result = await client.research('garden', { scope: 'a' });
    expect(result.sources[0]!.originalURL).toBe(originalURL);
    expect(result.sources[0]!.url).toBe('https://example.org/gardens');
    expect((await client.research('garden', { scope: 'a' })).sources[0]).toMatchObject({
      originalURL,
      cached: true,
    });
  });
  it('retains provider publication dates with attribution and prefers actual page metadata', async () => {
    const hits = [
      {
        title: 'Garden',
        url: 'https://example.org/gardens',
        snippet: 'garden',
        publishedAt: '2026-01-02',
      },
    ];
    const client = new ResearchClient(fixtureSearchProvider(hits), async (url) => ({
      html: '<article>garden</article>',
      finalURL: url,
      retrievedAt: '2026-10-09T00:00:00Z',
    }));
    expect((await client.research('garden', { scope: 'a' })).sources[0]).toMatchObject({
      publishedAt: '2026-01-02',
      publicationDateSource: 'search-provider',
    });
    const page = extractHTML(
      '<meta property="article:published_time" content="2026-02-01"><p>garden</p>',
      { originalURL: hits[0]!.url, providerPublishedAt: '2026-01-02' },
    );
    expect(page).toMatchObject({
      publishedAt: '2026-02-01',
      publicationDateSource: 'page-metadata',
    });
    expect(
      extractHTML('<p>garden</p>', { originalURL: hits[0]!.url, providerPublishedAt: 'unknown' })
        .publishedAt,
    ).toBeUndefined();
  });
});
