import { afterEach, describe, expect, it } from 'vitest';
import { mkdtemp, mkdir, rm, writeFile, symlink } from 'node:fs/promises';
import path from 'node:path';
import {
  archiveInterruptedHandoff,
  enqueueHandoff,
  handoffReceipt,
  pendingHandoff,
  respondHandoff,
} from '../../tools/agents/handoff-request';
const roots: string[] = [];
afterEach(async () => {
  for (const root of roots.splice(0)) await rm(root, { recursive: true, force: true });
});
async function fixture() {
  const base = path.join(process.cwd(), '.kit', 'inbox-tests');
  await mkdir(base, { recursive: true });
  const root = await mkdtemp(path.join(base, 'request-'));
  roots.push(root);
  return root;
}
describe('local handoff control inbox', () => {
  it('keeps one pending request and exposes only complete, idempotent receipts', async () => {
    const root = await fixture(),
      request = await enqueueHandoff(root, 'demo', 'agent-b', 'alice');
    expect((await pendingHandoff(root, 'demo'))?.id).toBe(request.id);
    await expect(enqueueHandoff(root, 'demo', 'agent-c', 'alice')).rejects.toThrow(
      'pending or incomplete',
    );
    const readers = Array.from({ length: 20 }, async () =>
      handoffReceipt(root, 'demo', request.id),
    );
    await respondHandoff(
      root,
      'demo',
      request,
      'offered',
      'Successor designated; not yet acquired',
    );
    for (const receipt of await Promise.all(readers))
      if (receipt) expect(receipt.status).toBe('offered');
    await respondHandoff(root, 'demo', request, 'offered', 'Same receipt retry');
    expect((await handoffReceipt(root, 'demo', request.id))?.status).toBe('offered');
    expect(await pendingHandoff(root, 'demo')).toBeUndefined();
  });
  it('recognizes a durable receipt after a crash before request cleanup without replaying transfer', async () => {
    const root = await fixture(),
      request = await enqueueHandoff(root, 'demo', 'agent-b', 'alice');
    const directory = path.join(root, '.kit', 'orchestration', 'demo');
    await writeFile(
      path.join(directory, `handoff-receipt-${request.id}.json`),
      JSON.stringify({ id: request.id, status: 'offered', message: 'Committed before crash' }),
    );
    expect(await pendingHandoff(root, 'demo')).toBeUndefined();
    expect((await enqueueHandoff(root, 'demo', 'agent-c', 'alice')).id).not.toBe(request.id);
  });
  it('archives an incomplete inbox explicitly and ignores half-written receipt temps', async () => {
    const root = await fixture(),
      folder = path.join(root, '.kit', 'orchestration', 'demo', 'handoff-request');
    await mkdir(folder, { recursive: true });
    await writeFile(path.join(folder, 'request.tmp'), '{');
    expect(await pendingHandoff(root, 'demo')).toBeUndefined();
    await expect(enqueueHandoff(root, 'demo', 'agent-b', 'alice')).rejects.toThrow('incomplete');
    expect(await archiveInterruptedHandoff(root, 'demo')).toMatch(/^handoff-request\.interrupted-/);
    const request = await enqueueHandoff(root, 'demo', 'agent-b', 'alice');
    await writeFile(
      path.join(path.dirname(folder), `handoff-receipt-${request.id}.json.interrupted.tmp`),
      '{',
    );
    expect(await handoffReceipt(root, 'demo', request.id)).toBeUndefined();
  });
  it('rejects invalid targets before claiming a slot and refuses symlinked inboxes', async () => {
    const root = await fixture();
    await expect(enqueueHandoff(root, 'demo', '../escape', 'alice')).rejects.toThrow();
    const folder = path.join(root, '.kit', 'orchestration', 'demo', 'handoff-request');
    await mkdir(path.dirname(folder), { recursive: true });
    const outside = await fixture();
    await symlink(outside, folder, process.platform === 'win32' ? 'junction' : 'dir');
    await expect(enqueueHandoff(root, 'demo', 'agent-b', 'alice')).rejects.toThrow('symlink');
  });
});
