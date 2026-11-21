import { test, expect } from '@playwright/test';
import { readFile, mkdir } from 'node:fs/promises';
import path from 'node:path';

test('base: real transform, empty input, bounded API errors', async ({ page, request }) => {
  await page.goto('http://127.0.0.1:3960');
  await page.getByLabel('Your input').fill('  Hello    team  ');
  await page.getByRole('button', { name: 'Normalize text' }).click();
  await expect(page.locator('.output-text')).toHaveText('Hello team');
  await page.getByLabel('Your input').fill('');
  await page.getByRole('button', { name: 'Normalize text' }).click();
  await expect(page.locator('.output-text')).toContainText('input is empty');
  const bad = await request.post('http://127.0.0.1:3960/api/transform', { data: { text: 4 } });
  expect(bad.status()).toBe(400);
  expect((await bad.json()).error.requestId).toBeTruthy();
});
test('documents: evidence, invalid review, honest CSV/PDF export and revocable sharing', async ({
  page,
}) => {
  await page.goto('/document');
  const budget = page
    .locator('.field-list article')
    .filter({ has: page.locator('.field-label strong', { hasText: 'Budget' }) });
  await budget.getByRole('button', { name: 'Inspect source' }).click();
  await expect(page.locator('mark')).toContainText('2,400');
  await budget.getByRole('button', { name: 'Edit', exact: true }).click();
  await budget.getByLabel('Reviewed value').fill('not a number');
  await budget.getByRole('button', { name: 'Save review' }).click();
  await expect(budget.getByRole('alert')).toBeVisible();
  await expect(budget.getByLabel('Reviewed value')).toHaveValue('not a number');
  await budget.getByLabel('Reviewed value').fill('999');
  await budget.getByRole('button', { name: 'Save review' }).click();
  await expect(budget).toContainText('not supported by original source');
  const csvPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export CSV', exact: true }).click();
  const csv = await csvPromise;
  const text = await readFile((await csv.path())!, 'utf8');
  expect(text).toContain('NOT supported by source');
  expect(text).toContain('999');
  const pdfPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download report' }).click();
  const pdf = await pdfPromise;
  expect((await readFile((await pdf.path())!)).subarray(0, 5).toString()).toBe('%PDF-');
  await page.getByRole('button', { name: 'Create local share link' }).click();
  const link = page.getByRole('link', { name: 'Open shared report' });
  await expect(link).toBeVisible();
  const href = (await link.getAttribute('href'))!;
  const shared = await page.request.get(href);
  expect(shared.status()).toBe(200);
  expect(await shared.text()).toContain('NOT supported');
  await page.getByRole('button', { name: 'Revoke link' }).click();
  await expect(link).toHaveCount(0);
  expect((await page.request.get(href)).status()).toBe(404);
  await page.getByRole('button', { name: 'What is the budget?' }).click();
  await expect(page.locator('.kit-chat-output')).toContainText('2,400');
  await expect(page.locator('.kit-chat').getByRole('button', { name: /Source 1/ })).toBeVisible();
});
test('documents: Unicode upload clears stale chat; malformed file recovers', async ({ page }) => {
  await page.goto('/document');
  await page.getByRole('button', { name: 'What is the budget?' }).click();
  await expect(page.locator('.kit-chat-output')).toBeVisible();
  await page.getByLabel('Upload document').setInputFiles({
    name: '文件.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('Organization: Unicode Team\nBudget: $42\n'),
  });
  await expect(page.locator('.kit-metric').first()).toContainText('文件.txt');
  await expect(page.locator('.kit-chat-output')).toHaveCount(0);
  await expect(page.locator('.kit-source')).toContainText('Budget: $42');
  await page.getByLabel('Upload document').setInputFiles({
    name: 'broken.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('broken'),
  });
  await expect(page.locator('main').getByRole('alert')).toContainText(/Invalid|Could not|corrupt/i);
  await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible();
  await page
    .getByLabel('Upload document')
    .setInputFiles({ name: 'empty.txt', mimeType: 'text/plain', buffer: Buffer.from('') });
  await expect(page.locator('.kit-metric').first()).toContainText('empty.txt');
  await expect(page.locator('.field-list')).toContainText('missing');
});
test('group: constraints and two real WebSocket clients share votes', async ({ page, context }) => {
  await page.goto('/group');
  await page.getByLabel('Maximum cost', { exact: true }).fill('0');
  await expect(page.getByText('No choice meets every constraint')).toBeVisible();
  await page.getByRole('button', { name: 'Reset local sample' }).click();
  const second = await context.newPage();
  await second.goto('/group');
  await second.getByLabel('Voting as').selectOption('sam');
  const room = `browser-${Date.now()}`;
  for (const tab of [page, second]) {
    await tab.getByText('Connect a second browser', { exact: true }).click();
    await tab.getByLabel('WebSocket server').fill('ws://127.0.0.1:3787');
    await tab.getByLabel('Room', { exact: true }).fill(room);
    await tab.getByRole('button', { name: 'Connect room', exact: true }).click();
    await expect(tab.getByRole('status')).toContainText('connected');
  }
  await page.getByRole('button', { name: 'Vote for Garden picnic', exact: true }).click();
  await expect(second.locator('.choice-card').filter({ hasText: 'Garden picnic' })).toContainText(
    '1 vote',
  );
  await second.getByRole('button', { name: 'Vote for Garden picnic', exact: true }).click();
  await expect(page.locator('.choice-card').filter({ hasText: 'Garden picnic' })).toContainText(
    '2 votes',
  );
  await second.close();
});
test('media: denied permissions, real image preprocessing, worker complete and cancel', async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {
      value: async () => {
        throw new DOMException('Denied for test', 'NotAllowedError');
      },
    });
  });
  await page.goto('/media');
  await page.getByRole('button', { name: 'Start recording', exact: true }).click();
  await expect(page.locator('main').getByRole('alert')).toContainText(/denied/i);
  await page.getByRole('button', { name: 'Open camera', exact: true }).click();
  await expect(page.locator('main').getByRole('alert').last()).toContainText(/denied/i);
  await page
    .getByLabel('Upload image', { exact: true })
    .setInputFiles(path.resolve('modules/documents/fixtures/scanned.png'));
  await expect(page.getByAltText('Your preprocessed upload')).toBeVisible();
  await expect(page.getByText('Your image · preprocessed locally')).toBeVisible();
  await page.getByRole('button', { name: 'Load sample transcript' }).click();
  await page.getByRole('button', { name: 'Process text in worker' }).click();
  await expect(page.locator('.kit-job')).toContainText('succeeded');
  await expect(page.locator('.local-result')).toContainText('lines');
  await page
    .getByLabel('Transcript workspace', { exact: true })
    .fill(Array.from({ length: 20 }, (_, i) => `line ${i}`).join('\n'));
  await page.getByRole('button', { name: 'Process text in worker' }).click();
  await page.getByRole('button', { name: 'Cancel job' }).click();
  await expect(page.locator('.kit-job')).toContainText('cancelled');
});
test('gallery: filter/sort/page, editable validation, error recovery and mobile layout', async ({
  page,
}) => {
  await page.goto('/gallery');
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page.getByText('Page 2 of 2', { exact: false })).toBeVisible();
  await page.getByLabel('Filter results').fill('garden');
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await page.getByRole('button', { name: 'error', exact: true }).click();
  await expect(page.locator('main').getByRole('alert')).toBeVisible();
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.getByText('Nothing here just yet.')).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  for (const url of ['/document', '/group', '/media', '/gallery']) {
    await page.goto(url);
    await expect(page.locator('h1')).toBeVisible();
    const size = await page.evaluate(() => ({
      width: document.documentElement.scrollWidth,
      viewport: innerWidth,
    }));
    expect(size.width).toBeLessThanOrEqual(size.viewport + 1);
  }
  await mkdir('.kit/verification/screenshots', { recursive: true });
  await page.screenshot({
    path: '.kit/verification/screenshots/gallery-mobile.png',
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/document');
  await page.screenshot({
    path: '.kit/verification/screenshots/document-desktop.png',
    fullPage: true,
  });
});
test('demo reset clears actual shares/jobs and refuses external origins', async ({ request }) => {
  const origin = 'http://127.0.0.1:3961';
  const share = await request.post('/api/kit/share', {
    headers: { origin },
    data: {
      title: 'Reset test',
      summary: 'Synthetic only',
      documents: [],
      citations: [],
      confirmed: true,
    },
  });
  expect(share.status()).toBe(200);
  const link = (await share.json()).url;
  const job = await request.post('/api/kit/jobs', {
    data: { type: 'ingest', input: { lines: ['one', 'two'], delayMs: 500 } },
  });
  expect(job.ok()).toBeTruthy();
  const id = (await job.json()).id;
  const denied = await request.post('/api/kit/reset', {
    headers: { origin: 'https://example.com', 'x-kit-demo-reset': 'confirm' },
  });
  expect(denied.status()).toBe(403);
  const reset = await request.post('/api/kit/reset', {
    headers: { origin, 'x-kit-demo-reset': 'confirm' },
  });
  expect(reset.status()).toBe(200);
  expect((await request.get(link)).status()).toBe(404);
  expect((await request.get(`/api/kit/jobs?id=${id}`)).status()).toBe(404);
});

test('optional AI: labeled fixture works; live remains explicitly disabled', async ({ page }) => {
  await page.goto('/ai');
  await page.getByRole('button', { name: 'Try fixture', exact: true }).click();
  await expect(page.getByText('Fixture preview:', { exact: false })).toBeVisible();
  const response = await page.request.post('/api/kit/ai', {
    headers: { origin: 'http://127.0.0.1:3961' },
    data: { text: 'Synthetic test', mode: 'live', confirmUsage: true },
  });
  expect(response.status()).toBe(403);
  expect((await response.json()).error.code).toBe('LIVE_DISABLED');
});
