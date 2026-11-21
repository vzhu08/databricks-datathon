import { z } from 'zod';
import { httpJson } from '../../../packages/runtime/src/index';
/** Runnable narrow adapter template: inject the actual sponsor endpoint and its documented schema. */
export function sponsorSearch<T>(config: {
  endpoint: URL;
  apiKey: string;
  responseSchema: z.ZodType<T>;
  fetcher?: typeof fetch;
}) {
  if (config.endpoint.protocol !== 'https:' && config.endpoint.hostname !== '127.0.0.1')
    throw new Error('Sponsor endpoint requires HTTPS');
  return async (query: string, signal?: AbortSignal) => {
    z.string().min(1).max(500).parse(query);
    const url = new URL(config.endpoint);
    url.searchParams.set('q', query);
    return httpJson(url, config.responseSchema, {
      headers: { authorization: `Bearer ${config.apiKey}` },
      fetcher: config.fetcher,
      signal,
      retries: 1,
      timeoutMs: 10_000,
      maxResponseBytes: 1_000_000,
    });
  };
}
