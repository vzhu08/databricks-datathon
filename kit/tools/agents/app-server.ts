import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { EventEmitter } from 'node:events';
import { z } from 'zod';

const EnvelopeSchema = z.object({
  id: z.union([z.string(), z.number()]).optional(),
  method: z.string().optional(),
  params: z.unknown().optional(),
  result: z.unknown().optional(),
  error: z
    .object({ code: z.number(), message: z.string(), data: z.unknown().optional() })
    .optional(),
});
export type RpcId = string | number;
export type ServerRequest = { id: RpcId; method: string; params: unknown };
export type Notification = { method: string; params: any };
export type ToolDefinition = {
  type: 'function';
  name: string;
  description: string;
  inputSchema: unknown;
};
export type TurnResult = { id: string; status: 'completed' | 'interrupted'; text: string };
export interface AppServerOptions {
  cwd?: string;
  command?: string;
  args?: string[];
  spawn?: typeof spawn;
  requestTimeoutMs?: number;
  maxFrameBytes?: number;
  signal?: AbortSignal;
}

/** Resolve npm's Windows shim to its JavaScript entrypoint without a shell. */
export function codexCommand(
  env = process.env,
  platform = process.platform,
): { command: string; args: string[] } {
  if (platform !== 'win32') return { command: 'codex', args: [] };
  const dirs = (env.PATH ?? env.Path ?? '').split(path.delimiter);
  if (env.APPDATA) dirs.push(path.join(env.APPDATA, 'npm'));
  for (const dir of dirs) {
    const native = path.join(dir, 'codex.exe');
    if (existsSync(native)) return { command: native, args: [] };
    const entry = path.join(dir, 'node_modules', '@openai', 'codex', 'bin', 'codex.js');
    if (existsSync(entry)) {
      const target =
        process.arch === 'arm64' ? 'aarch64-pc-windows-msvc' : 'x86_64-pc-windows-msvc';
      const platformPackage = `@openai/codex-win32-${process.arch}`;
      let vendorRoot = path.join(path.dirname(entry), '..', 'vendor');
      try {
        vendorRoot = path.join(
          path.dirname(createRequire(entry).resolve(`${platformPackage}/package.json`)),
          'vendor',
        );
      } catch {}
      const binary = path.join(vendorRoot, target, 'bin', 'codex.exe');
      if (existsSync(binary)) return { command: binary, args: [] };
      return { command: process.execPath, args: [entry] };
    }
  }
  throw new Error('Codex executable not found. Install @openai/codex and restart this terminal.');
}

/** JSONL RPC only. No transcript scraping or credential file access. */
export class AppServer extends EventEmitter {
  private child?: ChildProcessWithoutNullStreams;
  private nextId = 1;
  private pending = new Map<
    RpcId,
    { resolve: (result: unknown) => void; reject: (error: Error) => void; timer: NodeJS.Timeout }
  >();
  private stopped?: Error;
  private buffer = '';
  private initialized = false;
  private active?: { threadId: string; turnId?: string };
  private abortListener?: () => void;
  onServerRequest?: (request: ServerRequest) => Promise<unknown>;

  constructor(private readonly options: AppServerOptions = {}) {
    super();
  }

  async start() {
    if (this.child || this.stopped) throw new Error('App-server client cannot be started twice');
    this.options.signal?.throwIfAborted();
    const resolved = this.options.command
      ? { command: this.options.command, args: this.options.args ?? [] }
      : codexCommand();
    const env = { ...process.env };
    delete env.OPENAI_API_KEY;
    delete env.CODEX_API_KEY;
    this.child = (this.options.spawn ?? spawn)(
      resolved.command,
      [
        ...resolved.args,
        'app-server',
        '--listen',
        'stdio://',
        '-c',
        'model_provider="openai"',
        '-c',
        'forced_login_method="chatgpt"',
        '-c',
        'features.multi_agent=false',
        '-c',
        'features.multi_agent_v2=false',
      ],
      {
        cwd: this.options.cwd,
        stdio: 'pipe',
        windowsHide: true,
        detached: process.platform !== 'win32',
        env,
        shell: false,
      },
    ) as ChildProcessWithoutNullStreams;
    this.child.stdout.setEncoding('utf8');
    this.child.stdout.on('data', (chunk: string) => this.read(chunk));
    // stderr can contain private paths/account data. Drain without echoing or saving it.
    this.child.stderr.resume();
    this.child.on('error', (error) =>
      this.fail(new Error(`App-server process failed: ${error.message}`)),
    );
    this.child.on('exit', (code, signal) =>
      this.fail(
        new Error(
          `App-server offline (${signal ?? code ?? 'unknown'}). Pending server approvals were interrupted; reconnect to reissue them.`,
        ),
        false,
      ),
    );
    this.abortListener = () => this.close();
    this.options.signal?.addEventListener('abort', this.abortListener, { once: true });
    await this.request('initialize', {
      clientInfo: {
        name: 'hackathon_kit_orchestration',
        title: 'Hackathon Kit orchestration',
        version: '0.1.0',
      },
      capabilities: { experimentalApi: true },
    });
    this.send({ method: 'initialized', params: {} });
    this.initialized = true;
    const account = z
      .object({ account: z.object({ type: z.string() }).nullable() })
      .parse(await this.request('account/read', { refreshToken: false }));
    if (account.account?.type !== 'chatgpt') {
      this.close();
      throw new Error(
        'Local ChatGPT authentication required. Run codex login on this computer with your own ChatGPT account; API-key authentication is disabled.',
      );
    }
  }

  async request<T = unknown>(method: string, params: unknown = {}): Promise<T> {
    if (this.stopped) throw this.stopped;
    if (!this.child) throw new Error('App-server is not started');
    if (this.pending.size >= 100) throw new Error('App-server pending request limit reached');
    const id = this.nextId++;
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(
          new Error(
            `App-server request timed out: ${method}. Delivery may be uncertain; no automatic retry.`,
          ),
        );
      }, this.options.requestTimeoutMs ?? 30_000);
      this.pending.set(id, { resolve: (value) => resolve(value as T), reject, timer });
      try {
        this.send({ id, method, params });
      } catch (error) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(error);
      }
    });
  }

  private send(message: unknown) {
    if (this.stopped || !this.child?.stdin.writable)
      throw this.stopped ?? new Error('App-server stdin unavailable');
    const line = JSON.stringify(message) + '\n';
    if (Buffer.byteLength(line) > (this.options.maxFrameBytes ?? 2_000_000))
      throw new Error('App-server outbound frame too large');
    this.child.stdin.write(line, (error) => {
      if (error) this.fail(error);
    });
  }

  private read(chunk: string) {
    if (this.stopped) return;
    this.buffer += chunk;
    const max = this.options.maxFrameBytes ?? 2_000_000;
    if (Buffer.byteLength(this.buffer) > max && !this.buffer.includes('\n')) {
      this.fail(new Error('App-server inbound frame too large'));
      return;
    }
    let end: number;
    while ((end = this.buffer.indexOf('\n')) >= 0) {
      const line = this.buffer.slice(0, end).trim();
      this.buffer = this.buffer.slice(end + 1);
      if (!line) continue;
      if (Buffer.byteLength(line) > max) {
        this.fail(new Error('App-server inbound frame too large'));
        return;
      }
      let message: z.infer<typeof EnvelopeSchema>;
      try {
        message = EnvelopeSchema.parse(JSON.parse(line));
      } catch {
        this.fail(new Error('Invalid app-server JSONL protocol frame'));
        return;
      }
      if (message.method && message.id !== undefined) {
        const request = { id: message.id, method: message.method, params: message.params };
        void this.handleRequest(request);
      } else if (message.method) {
        this.emit('notification', { method: message.method, params: message.params });
      } else if (message.id !== undefined) {
        const pending = this.pending.get(message.id);
        if (!pending) continue;
        clearTimeout(pending.timer);
        this.pending.delete(message.id);
        if (message.error)
          pending.reject(
            new Error(
              `App-server RPC ${message.error.code}: ${message.error.message.slice(0, 1000)}`,
            ),
          );
        else pending.resolve(message.result);
      }
    }
    if (Buffer.byteLength(this.buffer) > max)
      this.fail(new Error('App-server inbound frame too large'));
  }

  private async handleRequest(request: ServerRequest) {
    try {
      if (!this.onServerRequest) throw new Error('No client handler for this server request');
      const result = await this.onServerRequest(request);
      if (!this.stopped) this.send({ id: request.id, result });
    } catch (error) {
      if (!this.stopped)
        this.send({
          id: request.id,
          error: {
            code: -32601,
            message: error instanceof Error ? error.message.slice(0, 1000) : 'Request rejected',
          },
        });
    }
  }

  async startThread(options: {
    model: string;
    cwd?: string;
    developerInstructions: string;
    dynamicTools?: ToolDefinition[];
    threadId?: string;
  }): Promise<string> {
    if (!this.initialized) throw new Error('App-server must initialize before starting a thread');
    const params = {
      model: options.model,
      cwd: options.cwd ?? this.options.cwd,
      approvalPolicy: 'on-request',
      sandbox: 'read-only',
      developerInstructions: options.developerInstructions,
      config: {
        model_reasoning_effort: 'high',
        'features.multi_agent': false,
        'features.multi_agent_v2': false,
      },
    };
    const response = z
      .object({ model: z.string(), thread: z.object({ id: z.string().min(1) }) })
      .parse(
        await this.request(
          options.threadId ? 'thread/resume' : 'thread/start',
          options.threadId
            ? { ...params, threadId: options.threadId, excludeTurns: true }
            : {
                ...params,
                allowProviderModelFallback: false,
                dynamicTools: options.dynamicTools ?? [],
              },
        ),
      );
    if (response.model !== options.model)
      throw new Error(
        `Requested ${options.model}; app-server selected ${response.model}. Model substitution refused.`,
      );
    return response.thread.id;
  }

  async runTurn(
    threadId: string,
    text: string,
    options: {
      model: string;
      effort?: 'medium' | 'high';
      timeoutMs?: number;
      onDelta?: (text: string) => void;
    },
  ): Promise<TurnResult> {
    if (this.active) throw new Error('A model turn is already active; queue the next input');
    if (!text.trim() || text.length > 100_000)
      throw new Error('Turn text must contain 1–100000 characters');
    this.active = { threadId };
    let accumulated = '';
    let turnId: string | undefined;
    let early: any;
    let rejectCompletion!: (error: Error) => void;
    let resolveCompletion!: (value: TurnResult) => void;
    let timer: NodeJS.Timeout | undefined;
    const completed = new Promise<TurnResult>((resolve, reject) => {
      resolveCompletion = resolve;
      rejectCompletion = reject;
    });
    // Consume early failure even if turn/start fails before completed is awaited.
    void completed.catch(() => {});
    const finish = (turn: any) => {
      if (turn.status === 'completed' || turn.status === 'interrupted')
        resolveCompletion({ id: turn.id, status: turn.status, text: accumulated });
      else
        rejectCompletion(
          new Error(
            `Model turn failed: ${String(turn.error?.message ?? turn.status).slice(0, 1500)}. Check model entitlement, quota, and local Codex login; no fallback was used.`,
          ),
        );
    };
    const listener = (notification: Notification) => {
      if (notification.params?.threadId !== threadId) return;
      if (
        notification.method === 'item/agentMessage/delta' &&
        typeof notification.params.delta === 'string'
      ) {
        if (turnId && notification.params.turnId !== turnId) return;
        const delta = notification.params.delta;
        if (accumulated.length + delta.length > 128_000) {
          rejectCompletion(new Error('Assistant output limit reached'));
          void this.interrupt();
          return;
        }
        accumulated += delta;
        options.onDelta?.(delta);
      }
      if (notification.method === 'turn/completed' && notification.params?.turn) {
        if (!turnId) early = notification.params.turn;
        else if (notification.params.turn.id === turnId) finish(notification.params.turn);
      }
    };
    const offline = (error: Error) => rejectCompletion(error);
    this.on('notification', listener);
    this.on('offline', offline);
    try {
      const response = z.object({ turn: z.object({ id: z.string().min(1) }) }).parse(
        await this.request('turn/start', {
          threadId,
          input: [{ type: 'text', text, text_elements: [] }],
          model: options.model,
          effort: options.effort ?? 'high',
          approvalPolicy: 'on-request',
          sandboxPolicy: { type: 'readOnly', networkAccess: false },
        }),
      );
      turnId = response.turn.id;
      this.active = { threadId, turnId };
      if (early?.id === turnId) finish(early);
      timer = setTimeout(() => {
        rejectCompletion(
          new Error('Model turn timed out; interruption requested. Pending input remains local.'),
        );
        void this.interrupt().catch(() => {});
      }, options.timeoutMs ?? 900_000);
      return await completed;
    } finally {
      if (timer) clearTimeout(timer);
      this.off('notification', listener);
      this.off('offline', offline);
      this.active = undefined;
    }
  }

  async interrupt() {
    if (!this.active?.turnId) throw new Error('No acknowledged active turn to interrupt');
    await this.request('turn/interrupt', {
      threadId: this.active.threadId,
      turnId: this.active.turnId,
    });
  }

  private terminateChild() {
    const child = this.child;
    if (!child) return;
    if (!child.pid) {
      child.kill();
      return;
    }
    if (process.platform === 'win32') {
      // The PID belongs to this live child. Include code-mode helpers so no
      // descendant can retain the client's pipes or keep a stopped chat alive.
      const killer = spawn('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], {
        stdio: 'ignore',
        windowsHide: true,
        shell: false,
      });
      killer.once('error', () => {
        child.kill();
      });
      killer.once('exit', (code) => {
        if (code !== 0) child.kill();
      });
      killer.unref();
    } else {
      try {
        process.kill(-child.pid, 'SIGTERM');
      } catch {
        child.kill();
      }
    }
  }

  private fail(error: Error, terminate = true) {
    if (this.stopped) return;
    this.stopped = error;
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.pending.clear();
    this.emit('offline', error);
    if (terminate) this.terminateChild();
    this.child?.stdin.destroy();
    this.child?.stdout.destroy();
    this.child?.stderr.destroy();
  }

  close() {
    this.options.signal?.removeEventListener('abort', this.abortListener ?? (() => {}));
    this.fail(
      new Error(
        'App-server closed. Unanswered process approvals were interrupted and must be reissued after reconnect.',
      ),
    );
  }
}
