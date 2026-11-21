import { it, expect } from 'vitest';
import { z } from 'zod';
import { readJSON, readRequestBytes } from '../packages/runtime/src/body';
import { normalizeText } from '../modules/documents/src/index';
import { extractFields, reviewExtraction } from '../modules/extraction/src/index';
import { reviewedReport } from '../examples/document-workbench/model';
import { POST as report } from '../examples/document-workbench/routes/report';
import { configuredLiveAI } from '../tools/live-policy';
import { authorizeDemoReset } from '../packages/runtime/src/demo-reset';

it('bounds streamed request bytes, malformed UTF-8/JSON and cancellation before parsing', async () => {
  const request = new Request('http://localhost', {
    method: 'POST',
    body: new ReadableStream({
      start(c) {
        c.enqueue(new Uint8Array(11));
        c.close();
      },
    }),
    duplex: 'half',
  } as RequestInit);
  await expect(readJSON(request, z.unknown(), 10)).rejects.toMatchObject({ status: 413 });
  await expect(
    readJSON(new Request('http://localhost', { method: 'POST', body: '{' }), z.unknown()),
  ).rejects.toMatchObject({ status: 400 });
  await expect(
    readJSON(
      new Request('http://localhost', { method: 'POST', body: new Uint8Array([255]) }),
      z.unknown(),
    ),
  ).rejects.toMatchObject({ status: 400 });
  const controller = new AbortController();
  const stalled = new Request('http://localhost', {
    method: 'POST',
    body: new ReadableStream({}),
    signal: controller.signal,
    duplex: 'half',
  } as RequestInit);
  const pending = readRequestBytes(stalled, 10, 1000);
  controller.abort();
  await expect(pending).rejects.toMatchObject({ status: 408 });
});
it('reviewed export never relabels an unsupported human value as original evidence', () => {
  const doc = normalizeText({ filename: 'source.txt', text: 'Budget: $2400\n' });
  const result = reviewExtraction(
    extractFields(doc),
    { key: 'budget', value: '999', editor: 'reviewer', note: 'Proposal' },
    doc,
  );
  const output = reviewedReport(doc, result);
  const budget = output.rows.find((r) => r.field === 'Budget')!;
  expect(budget.value).toBe(999);
  expect(budget.review).toContain('NOT supported');
  expect(output.report.summary).toContain('NOT supported');
  expect(budget.evidence).toContain('2400');
});
it('report API rejects malformed, oversized and fabricated citation input', async () => {
  expect(
    (await report(new Request('http://localhost', { method: 'POST', body: '{' }))).status,
  ).toBe(400);
  expect(
    (await report(new Request('http://localhost', { method: 'POST', body: ' '.repeat(500001) })))
      .status,
  ).toBe(413);
  const doc = normalizeText({ filename: 'source.txt', text: 'Budget: $20' });
  const response = await report(
    new Request('http://localhost', {
      method: 'POST',
      body: JSON.stringify({
        title: 'test',
        documents: [doc],
        citations: [{ documentId: doc.id, start: 0, end: 6, quote: 'fake!!' }],
      }),
    }),
  );
  expect(response.status).toBeGreaterThanOrEqual(400);
});
it('live tools require explicit opt-in and valid bounded configuration before creating an adapter', () => {
  expect(() => configuredLiveAI({ enabled: false, confirmed: true, maxCalls: 1 }, {})).toThrow(
    'both',
  );
  expect(() => configuredLiveAI({ enabled: true, confirmed: false, maxCalls: 1 }, {})).toThrow(
    'both',
  );
  expect(() => configuredLiveAI({ enabled: true, confirmed: true, maxCalls: 11 }, {})).toThrow();
  expect(() => configuredLiveAI({ enabled: true, confirmed: true, maxCalls: 1 }, {})).toThrow(
    'AI_MODEL',
  );
  expect(() =>
    configuredLiveAI({ enabled: true, confirmed: true, maxCalls: 1 }, { AI_MODEL: 'test' }),
  ).toThrow('OPENAI_API_KEY');
});
it('demo reset requires an explicit loopback, same-origin request', () => {
  expect(() =>
    authorizeDemoReset(
      new Request('https://example.com/api/kit/reset', {
        method: 'POST',
        headers: { origin: 'https://example.com', 'x-kit-demo-reset': 'confirm' },
      }),
    ),
  ).toThrow();
  expect(() =>
    authorizeDemoReset(
      new Request('http://localhost/api/kit/reset', {
        method: 'POST',
        headers: { origin: 'https://example.com', 'x-kit-demo-reset': 'confirm' },
      }),
    ),
  ).toThrow();
  expect(() =>
    authorizeDemoReset(
      new Request('http://localhost/api/kit/reset', {
        method: 'POST',
        headers: { origin: 'http://localhost', 'x-kit-demo-reset': 'confirm' },
      }),
    ),
  ).not.toThrow();
});
