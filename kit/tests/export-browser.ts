/** Usage: node --import tsx tests/export-browser.ts /absolute/generated-project */
import { spawn, type ChildProcess } from 'node:child_process';
import { once } from 'node:events';
import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { chromium, expect } from '@playwright/test';
if (!process.argv[2])
  throw new Error(
    'Pass an exported project root after installing/building it; Python recipe also needs uv sync --frozen.',
  );
const target = path.resolve(process.argv[2]);
const record = JSON.parse(await readFile(path.join(target, 'kit.project.json'), 'utf8'));
const children: ChildProcess[] = [];
let errors = '';
function start(command: string, args: string[], cwd: string, extra: Record<string, string> = {}) {
  const child = spawn(command, args, {
    cwd,
    env: { ...process.env, ...extra, RUN_LIVE_AI: 'false' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  children.push(child);
  child.stderr?.on('data', (v) => {
    errors += v;
  });
  return child;
}
async function ready(url: string) {
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 50));
  }
  throw new Error('Server not ready: ' + errors);
}
let browser;
try {
  if (record.starter === 'document-python') {
    const python = path.join(target, 'starters/python/.venv/bin/python');
    assert(
      await stat(python).catch(() => null),
      'Run uv sync --frozen in the exported Python starter first',
    );
    start(
      python,
      ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '3971'],
      path.join(target, 'starters/python'),
    );
    await ready('http://127.0.0.1:3971/ready');
  }
  start(
    process.execPath,
    ['node_modules/next/dist/bin/next', 'start', '--hostname', '127.0.0.1', '--port', '3970'],
    target,
    { PYTHON_API_URL: 'http://127.0.0.1:3971' },
  );
  await ready('http://127.0.0.1:3970/api/health');
  browser = await chromium.launch();
  const page = await browser.newPage();
  if (record.starter === 'document-python') {
    await page.goto('http://127.0.0.1:3970/kit');
    await page.getByLabel('Python input').fill('  Exported   🌱  browser   flow  ');
    await page.getByRole('button', { name: 'Normalize with Python' }).click();
    await expect(page.getByLabel('Python result')).toHaveText('Exported 🌱 browser flow');
  }
  if (record.closure.includes('ai')) {
    await page.goto('http://127.0.0.1:3970/ai');
    await page.getByRole('button', { name: 'Try fixture', exact: true }).click();
    await expect(page.getByText('Fixture preview:', { exact: false })).toBeVisible();
  }
  console.log(
    JSON.stringify({
      target,
      starter: record.starter,
      status: 'passed',
      flow:
        record.starter === 'document-python'
          ? 'Browser → exported Next route → exported Python service → validated UI result'
          : 'Browser → exported optional AI route → labeled fixture',
    }),
  );
} finally {
  await browser?.close();
  for (const child of children.reverse()) {
    child.kill('SIGTERM');
    if (child.exitCode === null) await once(child, 'exit');
  }
}
