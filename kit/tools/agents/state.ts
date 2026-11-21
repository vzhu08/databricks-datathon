import { mkdir, open, readFile, rename, unlink, lstat } from 'node:fs/promises';
import path from 'node:path';
import { hostname } from 'node:os';
import { randomUUID } from 'node:crypto';
import { PlanSchema, TaskSchema, type RunState } from './contracts';
import { SharedContextSchema } from './handoff-contracts';

export class StateStore {
  readonly directory: string;
  private lockToken?: string;
  constructor(root: string, runId: string) {
    if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(runId)) throw new Error('Invalid run ID');
    this.directory = path.join(root, '.kit', 'orchestration', runId);
  }
  private async boundary() {
    let current = path.parse(path.resolve(this.directory)).root;
    for (const part of path.relative(current, this.directory).split(path.sep)) {
      current = path.join(current, part);
      const info = await lstat(current).catch((e) => {
        if (e.code !== 'ENOENT') throw e;
      });
      if (info?.isSymbolicLink()) throw new Error(`State path cannot follow symlinks: ${current}`);
    }
    for (const file of ['state.json', 'coordinator.lock']) {
      const info = await lstat(path.join(this.directory, file)).catch((e) => {
        if (e.code !== 'ENOENT') throw e;
      });
      if (info?.isSymbolicLink()) throw new Error('State file cannot be a symlink');
    }
  }
  async load(): Promise<RunState | undefined> {
    await this.boundary();
    let raw: string;
    try {
      raw = await readFile(path.join(this.directory, 'state.json'), 'utf8');
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code === 'ENOENT') return;
      throw e;
    }
    if (Buffer.byteLength(raw) > 32_000_000) throw new Error('State exceeds 32 MB; archive run');
    const state = JSON.parse(raw) as RunState;
    if (
      state.schemaVersion !== 1 ||
      !Array.isArray(state.tasks) ||
      !Array.isArray(state.events) ||
      !Array.isArray(state.seenReports) ||
      !Array.isArray(state.notices) ||
      typeof state.paused !== 'boolean' ||
      !Number.isFinite(state.lastStatusAt)
    )
      throw new Error('Invalid persisted coordinator state');
    state.tasks.forEach((t) => TaskSchema.parse(t));
    if (state.plan) PlanSchema.parse(state.plan);
    if (state.context) SharedContextSchema.parse(state.context);
    if (
      state.events.some(
        (e, i) =>
          e.seq !== (state.eventBaseSeq ?? 0) + i + 1 ||
          typeof e.message !== 'string' ||
          !Number.isFinite(Date.parse(e.at)),
      )
    )
      throw new Error('Invalid event sequence');
    return state;
  }
  async save(state: RunState) {
    await this.boundary();
    await mkdir(this.directory, { recursive: true, mode: 0o700 });
    const filename = path.join(this.directory, 'state.json');
    const temporary = `${filename}.${randomUUID()}.tmp`;
    const handle = await open(temporary, 'wx', 0o600);
    try {
      await handle.writeFile(JSON.stringify(state, null, 2) + '\n');
      await handle.sync();
    } finally {
      await handle.close();
    }
    try {
      await rename(temporary, filename);
    } finally {
      await unlink(temporary).catch(() => {});
    }
  }
  async lock() {
    await this.boundary();
    await mkdir(this.directory, { recursive: true, mode: 0o700 });
    const token = randomUUID();
    try {
      const handle = await open(path.join(this.directory, 'coordinator.lock'), 'wx', 0o600);
      try {
        await handle.writeFile(JSON.stringify({ pid: process.pid, host: hostname(), token }));
      } finally {
        await handle.close();
      }
      this.lockToken = token;
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code === 'EEXIST')
        throw new Error(
          'Local coordinator already locked. Stop the previous process; use recover only after confirming the old coordinator stopped.',
          { cause: e },
        );
      throw e;
    }
  }
  async retainLocalSnapshot(state: RunState) {
    await this.boundary();
    await mkdir(this.directory, { recursive: true, mode: 0o700 });
    const name = `local-before-resume-${randomUUID()}.json`;
    const bytes = JSON.stringify(state, null, 2) + '\n';
    if (Buffer.byteLength(bytes) > 32_000_000)
      throw new Error('Local recovery snapshot exceeds 32 MB; archive explicitly before resuming');
    const handle = await open(path.join(this.directory, name), 'wx', 0o600);
    try {
      await handle.writeFile(bytes);
      await handle.sync();
    } finally {
      await handle.close();
    }
    return name;
  }
  async unlock() {
    await this.boundary();
    const filename = path.join(this.directory, 'coordinator.lock');
    if (!this.lockToken) return;
    const lock = JSON.parse(await readFile(filename, 'utf8'));
    if (lock.token !== this.lockToken) throw new Error('Local coordinator fencing token changed');
    await unlink(filename);
    this.lockToken = undefined;
  }
}
