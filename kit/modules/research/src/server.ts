import { lookup } from 'node:dns/promises';
import { request as httpRequest } from 'node:http';
import { request as httpsRequest } from 'node:https';
import ipaddr from 'ipaddr.js';
import { load } from 'cheerio';
import { z } from 'zod';
import { BoundedCache, httpJson, KitError } from '../../../packages/runtime/src/index';
import { normalizeURL, deduplicateResults, type SearchHit, type SearchProvider } from './index';
export type ResolvedAddress = { address: string; family: number };
export type Resolver = (hostname: string) => Promise<ResolvedAddress[]>;
export async function validateDestination(
  input: string,
  resolver: Resolver = (host) => lookup(host, { all: true }),
) {
  const url = new URL(normalizeURL(input));
  const host = url.hostname.replace(/^\[|\]$/g, '');
  if (host === 'localhost' || /\.(localhost|local|internal)$/i.test(host))
    throw new KitError('UNSAFE_URL', 'Local network destinations are blocked');
  const addresses = ipaddr.isValid(host)
    ? [{ address: host, family: ipaddr.parse(host).kind() === 'ipv4' ? 4 : 6 }]
    : await resolver(host);
  if (
    !addresses.length ||
    addresses.some(
      (a) => !ipaddr.isValid(a.address) || ipaddr.process(a.address).range() !== 'unicast',
    )
  )
    throw new KitError('UNSAFE_URL', 'Private, reserved or mixed DNS destinations are blocked');
  return { url, addresses };
}
export type SafeFetchOptions = {
  timeoutMs?: number;
  maxBytes?: number;
  maxRedirects?: number;
  signal?: AbortSignal;
  resolver?: Resolver;
};
/** DNS is validated and pinned into the request lookup. Every redirect is revalidated. */
export async function safeFetchHTML(
  input: string,
  options: SafeFetchOptions = {},
): Promise<{ html: string; finalURL: string; retrievedAt: string }> {
  const timeoutMs = z
    .number()
    .int()
    .min(1)
    .max(60_000)
    .parse(options.timeoutMs ?? 10_000);
  const signal = AbortSignal.any([
    AbortSignal.timeout(timeoutMs),
    ...(options.signal ? [options.signal] : []),
  ]);
  const maxBytes = z
      .number()
      .int()
      .min(1)
      .max(10_000_000)
      .parse(options.maxBytes ?? 2_000_000),
    maxRedirects = z
      .number()
      .int()
      .min(0)
      .max(5)
      .parse(options.maxRedirects ?? 3);
  let next = input;
  for (let hop = 0; hop <= maxRedirects; hop++) {
    signal.throwIfAborted();
    const { url, addresses } = await new Promise<Awaited<ReturnType<typeof validateDestination>>>(
      (resolve, reject) => {
        const abort = () => reject(signal.reason);
        signal.addEventListener('abort', abort, { once: true });
        validateDestination(next, options.resolver)
          .then(resolve, reject)
          .finally(() => signal.removeEventListener('abort', abort));
        if (signal.aborted) abort();
      },
    );
    signal.throwIfAborted();
    const result = await new Promise<{ redirect?: string; html?: string }>((resolve, reject) => {
      const requester = url.protocol === 'https:' ? httpsRequest : httpRequest;
      const req = requester(
        url,
        {
          signal,
          agent: false,
          headers: {
            'user-agent': 'HackathonKitResearch/1.0',
            accept: 'text/html,application/xhtml+xml',
            'accept-encoding': 'identity',
          },
          lookup: (_host, opts, callback) => {
            if (opts.all) callback(null, addresses);
            else callback(null, addresses[0]!.address, addresses[0]!.family);
          },
        },
        (res) => {
          if ([301, 302, 303, 307, 308].includes(res.statusCode ?? 0)) {
            res.destroy();
            resolve({ redirect: res.headers.location });
            return;
          }
          if (res.statusCode !== 200) {
            res.resume();
            reject(new KitError('FETCH_FAILED', `Source returned HTTP ${res.statusCode}`, 502));
            return;
          }
          if (
            !/^(text\/html|application\/xhtml\+xml)(;|$)/i.test(res.headers['content-type'] ?? '')
          ) {
            res.resume();
            reject(new KitError('UNSUPPORTED_CONTENT', 'Source must return HTML', 415));
            return;
          }
          const encoding = res.headers['content-encoding'];
          if (encoding && encoding !== 'identity') {
            res.destroy();
            reject(
              new KitError(
                'UNSUPPORTED_ENCODING',
                'Compressed source responses are not accepted',
                502,
              ),
            );
            return;
          }
          let length = 0;
          const chunks: Buffer[] = [];
          res.on('data', (chunk: Buffer) => {
            length += chunk.length;
            if (length > maxBytes) {
              req.destroy(new KitError('RESPONSE_TOO_LARGE', 'Source exceeded byte limit', 502));
              return;
            }
            chunks.push(chunk);
          });
          res.on('error', reject);
          res.on('end', () => resolve({ html: Buffer.concat(chunks).toString('utf8') }));
        },
      );
      req.on('error', reject);
      req.end();
    });
    if (result.html !== undefined)
      return { html: result.html, finalURL: url.href, retrievedAt: new Date().toISOString() };
    if (!result.redirect)
      throw new KitError('INVALID_REDIRECT', 'Source redirect has no location', 502);
    next = new URL(result.redirect, url).href;
  }
  throw new KitError('TOO_MANY_REDIRECTS', 'Source redirect limit exceeded', 502);
}
export function extractHTML(
  html: string,
  source: {
    originalURL: string;
    finalURL?: string;
    retrievedAt?: string;
    mode?: 'fixture' | 'live';
    providerPublishedAt?: string;
  },
) {
  if (Buffer.byteLength(html) > 2_000_000)
    throw new KitError('RESPONSE_TOO_LARGE', 'HTML exceeds extraction limit');
  const $ = load(html),
    title = $('title').first().text().trim();
  const date =
    $('meta[property="article:published_time"]').attr('content') ??
    $('time[datetime]').first().attr('datetime');
  const pageDate = date && !Number.isNaN(Date.parse(date)) ? date : undefined;
  const providerDate =
    source.providerPublishedAt && !Number.isNaN(Date.parse(source.providerPublishedAt))
      ? source.providerPublishedAt
      : undefined;
  const publishedAt = pageDate ?? providerDate;
  const publicationDateSource: 'page-metadata' | 'search-provider' | undefined = pageDate
    ? 'page-metadata'
    : providerDate
      ? 'search-provider'
      : undefined;
  $('script,style,nav,header,footer,noscript,iframe,form').remove();
  const root = $('article').first().length
    ? $('article').first()
    : $('main').first().length
      ? $('main').first()
      : $('body');
  root.find('p,h1,h2,h3,h4,li,br,tr').each((_, element) => {
    $(element).append('\n');
  });
  const text = root
    .text()
    .replace(/[\t ]+/g, ' ')
    .replace(/ *\n */g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
  return {
    title,
    text,
    originalURL: source.originalURL,
    url: normalizeURL(source.finalURL ?? source.originalURL),
    retrievedAt: source.retrievedAt ?? new Date().toISOString(),
    ...(publishedAt ? { publishedAt, publicationDateSource } : {}),
    mode: source.mode ?? 'live',
  };
}
export type ResearchSource = ReturnType<typeof extractHTML>;
export function tavilySearchProvider(
  apiKey: string,
  options: { fetcher?: typeof fetch } = {},
): SearchProvider {
  if (!apiKey) throw new KitError('CONFIGURATION', 'TAVILY_API_KEY is required', 503);
  return {
    name: 'tavily',
    mode: 'live',
    async search(query, input = {}) {
      const limit = z
        .number()
        .int()
        .min(1)
        .max(10)
        .parse(input.limit ?? 5);
      const response = await httpJson(
        'https://api.tavily.com/search',
        z.object({
          results: z.array(
            z.object({
              title: z.string(),
              url: z.string(),
              content: z.string(),
              published_date: z.string().optional(),
            }),
          ),
        }),
        {
          method: 'POST',
          headers: { authorization: `Bearer ${apiKey}`, 'content-type': 'application/json' },
          body: JSON.stringify({
            query: z.string().min(1).max(1000).parse(query),
            max_results: limit,
            search_depth: 'basic',
            include_answer: false,
          }),
          signal: input.signal,
          fetcher: options.fetcher,
        },
      );
      return deduplicateResults(
        response.results.map((r) => ({
          title: r.title,
          url: r.url,
          snippet: r.content,
          ...(r.published_date ? { publishedAt: r.published_date } : {}),
        })),
      ).slice(0, limit);
    },
  };
}
export class ResearchClient {
  private cache = new BoundedCache<ResearchSource>(50, 5 * 60_000);
  constructor(
    private provider: SearchProvider,
    private fetchPage: typeof safeFetchHTML = safeFetchHTML,
  ) {}
  async research(query: string, options: { scope: string; limit?: number; signal?: AbortSignal }) {
    if (!options.scope) throw new Error('Private user cache scope required');
    const limit = z
      .number()
      .int()
      .min(1)
      .max(10)
      .parse(options.limit ?? 5);
    const hits: SearchHit[] = deduplicateResults(
      await this.provider.search(query, { limit, signal: options.signal }),
    ).slice(0, limit);
    const sources: (ResearchSource & { cached: boolean })[] = [],
      failures: { url: string; message: string }[] = [];
    for (const hit of hits) {
      options.signal?.throwIfAborted();
      const cached = this.cache.get(options.scope, hit.url);
      if (cached) {
        sources.push({ ...cached, cached: true });
        continue;
      }
      try {
        const page = await this.fetchPage(hit.url, { signal: options.signal });
        const source = extractHTML(page.html, {
          originalURL: hit.originalURL ?? hit.url,
          providerPublishedAt: hit.publishedAt,
          finalURL: page.finalURL,
          retrievedAt: page.retrievedAt,
          mode: this.provider.mode,
        });
        this.cache.set(options.scope, hit.url, source);
        sources.push({ ...source, cached: false });
      } catch (error) {
        if (options.signal?.aborted) throw options.signal.reason;
        failures.push({
          url: hit.url,
          message: error instanceof Error ? error.message : 'Fetch failed',
        });
      }
    }
    return { query, provider: this.provider.name, mode: this.provider.mode, sources, failures };
  }
  clear(scope: string) {
    this.cache.invalidate(scope);
  }
}
