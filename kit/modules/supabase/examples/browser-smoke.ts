// Run against the standalone example in fixture mode. No provider calls are made.
import { chromium, expect } from '@playwright/test';
import { fixtureAccounts, fixturePassword } from './components/session';
const base = new URL(process.env.KIT_SUPABASE_EXAMPLE_URL ?? 'http://127.0.0.1:3004');
if (!['127.0.0.1', 'localhost'].includes(base.hostname) || base.protocol !== 'http:')
  throw new Error('Smoke test requires a local HTTP fixture example');
const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
});
const page = await browser.newPage();
const errors: string[] = [];
page.on('pageerror', (error) => errors.push(error.message));
try {
  await page.goto(base.href);
  await expect(page.getByText('SUPABASE MODULE · FIXTURE')).toBeVisible();
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByText('No notes yet.')).toBeVisible();
  await page.getByLabel('Title', { exact: true }).fill('Browser fixture');
  await page.getByLabel('Body', { exact: true }).fill('Private note');
  await page.getByRole('button', { name: 'Create note', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Browser fixture', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Edit Browser fixture' }).click();
  await page.getByLabel('Edit title', { exact: true }).fill('Edited fixture');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByRole('heading', { name: 'Edited fixture' })).toBeVisible();
  await page.getByText('Fixture accounts and failure controls').click();
  await page.getByLabel('Simulate request failure').check();
  await page.getByRole('button', { name: 'Refresh notes' }).click();
  await expect(page.getByRole('main').getByRole('alert')).toContainText(
    'Simulated request failure',
  );
  await page.getByLabel('Simulate request failure').uncheck();
  await page.getByRole('button', { name: 'Retry loading' }).click();
  await expect(page.getByRole('main').getByRole('alert')).toHaveCount(0);
  await page.getByLabel('Title', { exact: true }).fill('Unsubmitted Alice draft');
  await page.getByLabel('Body', { exact: true }).fill('Clear this on account switch');
  await page.getByRole('button', { name: 'Sign out' }).click();
  await page.getByLabel('Email', { exact: true }).fill(fixtureAccounts[1].email);
  await page.getByLabel('Password', { exact: true }).fill(fixturePassword);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByText('No notes yet.')).toBeVisible();
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('Body', { exact: true })).toHaveValue('');
  await expect(page.getByRole('heading', { name: 'Edited fixture' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Sign out' }).click();
  await page.getByLabel('Email', { exact: true }).fill(fixtureAccounts[0].email);
  await page.getByLabel('Password', { exact: true }).fill(fixturePassword);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('button', { name: 'Delete Edited fixture' }).click();
  await expect(page.getByText('No notes yet.')).toBeVisible();
  expect((await page.request.get(new URL('/api/notes', base).href)).status()).toBe(503);
  expect(errors).toEqual([]);
  if (process.env.KIT_EXAMPLE_SCREENSHOT)
    await page.screenshot({ path: process.env.KIT_EXAMPLE_SCREENSHOT, fullPage: true });
  console.log(
    'Fixture UI: sign-in, create, edit, failure/retry, account isolation, delete, disabled live route passed.',
  );
} finally {
  await browser.close();
}
