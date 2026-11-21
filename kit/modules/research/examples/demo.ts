import { readFile } from 'node:fs/promises';
import { ResearchClient } from '../src/server';
import { fixtureSearchProvider } from '../src/index';
import hits from '../fixtures/search.json';
const client = new ResearchClient(fixtureSearchProvider(hits), async (url) => ({
  html: await readFile(new URL('../fixtures/article.html', import.meta.url), 'utf8'),
  finalURL: url,
  retrievedAt: '2026-01-20T12:00:00Z',
}));
console.log(JSON.stringify(await client.research('garden', { scope: 'demo-user' }), null, 2));
