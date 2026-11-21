import { lstat, mkdir, open, readFile, rename, unlink, rmdir } from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { z } from 'zod';
import { Id } from './contracts';

const RequestSchema = z
  .object({
    id: z.string().uuid(),
    runId: Id,
    to: Id,
    actor: z.string().min(1).max(100),
    at: z.number().int(),
  })
  .strict();
const ReceiptSchema = z
  .object({
    id: z.string().uuid(),
    status: z.enum(['offered', 'rejected']),
    message: z.string().max(4000),
  })
  .strict();
export type HandoffRequest = z.infer<typeof RequestSchema>;
function directory(root: string, runId: string) {
  Id.parse(runId);
  return path.resolve(root, '.kit', 'orchestration', runId, 'handoff-request');
}
async function boundary(root: string) {
  let current = path.parse(root).root;
  for (const part of path.relative(current, root).split(path.sep)) {
    current = path.join(current, part);
    if ((await lstat(current).catch(() => undefined))?.isSymbolicLink())
      throw new Error('Handoff inbox cannot follow symlinks');
  }
}
export async function enqueueHandoff(root: string, runId: string, to: string, actor: string) {
  const request = RequestSchema.parse({ id: randomUUID(), runId, to, actor, at: Date.now() });
  const folder = directory(root, runId);
  await boundary(folder);
  await mkdir(path.dirname(folder), { recursive: true, mode: 0o700 });
  try {
    await mkdir(folder, { mode: 0o700 });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'EEXIST')
      throw new Error(
        'A local handoff request is pending or incomplete. Wait for its receipt; after stopping old coordinator/handoff processes, recover --confirm-stopped archives an interrupted inbox.',
        { cause: error },
      );
    throw error;
  }
  const temp = path.join(folder, 'request.tmp');
  const handle = await open(temp, 'wx', 0o600);
  try {
    await handle.writeFile(JSON.stringify(request));
    await handle.sync();
  } finally {
    await handle.close();
  }
  await rename(temp, path.join(folder, 'request.json'));
  return request;
}
export async function pendingHandoff(
  root: string,
  runId: string,
): Promise<HandoffRequest | undefined> {
  const folder = directory(root, runId);
  await boundary(folder);
  const file = path.join(folder, 'request.json');
  if ((await lstat(file).catch(() => undefined))?.isSymbolicLink())
    throw new Error('Handoff request cannot be a symlink');
  try {
    const raw = await readFile(file, 'utf8');
    if (raw.length > 4000) throw new Error('Handoff request too large');
    const request = RequestSchema.parse(JSON.parse(raw));
    if (await handoffReceipt(root, runId, request.id)) {
      await unlink(file);
      await rmdir(folder);
      return;
    }
    return request;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return;
    throw error;
  }
}
export async function respondHandoff(
  root: string,
  runId: string,
  request: HandoffRequest,
  status: 'offered' | 'rejected',
  message: string,
) {
  const folder = directory(root, runId);
  await boundary(folder);
  const receipt = ReceiptSchema.parse({ id: request.id, status, message });
  const target = path.join(path.dirname(folder), `handoff-receipt-${request.id}.json`);
  const previous = await handoffReceipt(root, runId, request.id);
  if (previous && previous.status !== status)
    throw new Error(
      'Conflicting handoff receipt; inspect shared leadership rather than replay transfer',
    );
  if (!previous) {
    const temporary = `${target}.${randomUUID()}.tmp`;
    const handle = await open(temporary, 'wx', 0o600);
    try {
      await handle.writeFile(JSON.stringify(receipt));
      await handle.sync();
    } finally {
      await handle.close();
    }
    try {
      await rename(temporary, target);
    } finally {
      await unlink(temporary).catch(() => {});
    }
  }
  const active = await pendingHandoff(root, runId);
  if (active && active.id === request.id) {
    await unlink(path.join(folder, 'request.json'));
    await rmdir(folder);
  }
}
export async function handoffReceipt(root: string, runId: string, id: string) {
  z.string().uuid().parse(id);
  const folder = directory(root, runId);
  await boundary(path.dirname(folder));
  const file = path.join(path.dirname(folder), `handoff-receipt-${id}.json`);
  if ((await lstat(file).catch(() => undefined))?.isSymbolicLink())
    throw new Error('Handoff receipt cannot be a symlink');
  try {
    return ReceiptSchema.parse(JSON.parse(await readFile(file, 'utf8')));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return;
    throw error;
  }
}
export async function archiveInterruptedHandoff(root: string, runId: string) {
  const folder = directory(root, runId);
  await boundary(folder);
  const archive = `${folder}.interrupted-${randomUUID()}`;
  try {
    await rename(folder, archive);
    return path.basename(archive);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return;
    throw error;
  }
}
