import { EventEmitter } from 'node:events';
import { PassThrough, Writable } from 'node:stream';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AppServer, type Notification } from '../../tools/agents/app-server';

type Frame = { id?: string | number; method?: string; params?: any; result?: any; error?: any };
const clients: AppServer[] = [];
afterEach(() => {
  for (const client of clients.splice(0)) client.close();
});
function harness(
  overrides: {
    account?: string;
    model?: string;
    ignore?: string;
    turnStatus?: string;
    early?: boolean;
  } = {},
) {
  const frames: Frame[] = [];
  const child = new EventEmitter() as any;
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  child.kill = vi.fn();
  const send = (frame: Frame) => child.stdout.write(JSON.stringify(frame) + '\n');
  child.stdin = new Writable({
    write(chunk, _encoding, callback) {
      for (const line of chunk.toString().trim().split('\n')) {
        const frame = JSON.parse(line) as Frame;
        frames.push(frame);
        if (frame.method === overrides.ignore) continue;
        let result: any;
        if (frame.method === 'initialize') result = {};
        else if (frame.method === 'account/read')
          result = { account: { type: overrides.account ?? 'chatgpt' } };
        else if (frame.method === 'thread/start' || frame.method === 'thread/resume')
          result = {
            thread: { id: frame.params.threadId ?? 'thread-1' },
            model: overrides.model ?? frame.params.model,
          };
        else if (frame.method === 'turn/start') {
          result = { turn: { id: 'turn-1' } };
          if (overrides.early) {
            send({
              method: 'item/agentMessage/delta',
              params: { threadId: frame.params.threadId, turnId: 'turn-1', delta: 'Hello' },
            });
            send({
              method: 'turn/completed',
              params: {
                threadId: frame.params.threadId,
                turn: {
                  id: 'turn-1',
                  status: overrides.turnStatus ?? 'completed',
                  error: { message: 'No model entitlement' },
                },
              },
            });
          }
        } else if (frame.method === 'turn/interrupt') result = {};
        if (frame.id !== undefined && result !== undefined)
          queueMicrotask(() => send({ id: frame.id, result }));
      }
      callback();
    },
  });
  const spawn = vi.fn(() => child) as any;
  const client = new AppServer({ command: 'mock-codex', spawn, requestTimeoutMs: 30 });
  clients.push(client);
  return { client, child, spawn, frames, send };
}

describe('official app-server protocol', () => {
  it('initializes once and requires local ChatGPT auth without exposing account data', async () => {
    const h = harness();
    await h.client.start();
    expect(h.frames.slice(0, 3).map((f) => f.method)).toEqual([
      'initialize',
      'initialized',
      'account/read',
    ]);
    expect(h.frames[0].params.capabilities.experimentalApi).toBe(true);
    expect(h.spawn.mock.calls[0][1]).toContain('forced_login_method="chatgpt"');
    expect(h.spawn.mock.calls[0][2].shell).toBe(false);
    expect(h.spawn.mock.calls[0][2].env.OPENAI_API_KEY).toBeUndefined();
    await expect(h.client.start()).rejects.toThrow('twice');
  });

  it('refuses API-key auth and silent model substitution', async () => {
    const keyed = harness({ account: 'apiKey' });
    await expect(keyed.client.start()).rejects.toThrow('ChatGPT authentication required');
    expect(keyed.child.kill).toHaveBeenCalled();
    const changed = harness({ model: 'different-model' });
    await changed.client.start();
    await expect(
      changed.client.startThread({ model: 'gpt-6-astra', developerInstructions: 'Lead' }),
    ).rejects.toThrow('substitution refused');
  });

  it('persists/resumes exact model read-only thread and streams an early completion', async () => {
    const h = harness({ early: true });
    await h.client.start();
    const threadId = await h.client.startThread({
      model: 'gpt-6-astra',
      developerInstructions: 'Lead',
      dynamicTools: [],
    });
    expect(threadId).toBe('thread-1');
    const params = h.frames.find((f) => f.method === 'thread/start')!.params;
    expect(params).toMatchObject({ sandbox: 'read-only', allowProviderModelFallback: false });
    const onDelta = vi.fn();
    expect(await h.client.runTurn(threadId, 'Hello', { model: 'gpt-6-astra', onDelta })).toEqual({
      id: 'turn-1',
      status: 'completed',
      text: 'Hello',
    });
    expect(onDelta).toHaveBeenCalledWith('Hello');
    expect(
      await h.client.startThread({ model: 'gpt-6-astra', developerInstructions: 'Lead', threadId }),
    ).toBe(threadId);
    expect(h.frames.find((f) => f.method === 'thread/resume')!.params.excludeTurns).toBe(true);
    expect(h.frames.find((f) => f.method === 'turn/start')!.params.input[0].text_elements).toEqual(
      [],
    );
  });

  it('reports failed entitlement as failure and never retries with a different model', async () => {
    const h = harness({ early: true, turnStatus: 'failed' });
    await h.client.start();
    await expect(h.client.runTurn('thread-1', 'Hello', { model: 'gpt-6-astra' })).rejects.toThrow(
      'No model entitlement',
    );
    expect(h.frames.filter((f) => f.method === 'turn/start')).toHaveLength(1);
  });

  it('handles dynamic server calls with exact RPC response id', async () => {
    const h = harness();
    await h.client.start();
    h.client.onServerRequest = async (request) => ({
      success: true,
      contentItems: [{ type: 'inputText', text: request.method }],
    });
    h.send({ id: 'server-request', method: 'item/tool/call', params: { tool: 'snapshot' } });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(h.frames.find((f) => f.id === 'server-request')?.result).toMatchObject({
      success: true,
    });
  });

  it('interrupts only acknowledged turns and treats interrupted as distinct', async () => {
    const h = harness();
    await h.client.start();
    await expect(h.client.interrupt()).rejects.toThrow('No acknowledged');
    const result = h.client.runTurn('thread-1', 'Hello', { model: 'gpt-6-astra' });
    await new Promise((resolve) => setTimeout(resolve, 0));
    await h.client.interrupt();
    h.send({
      method: 'turn/completed',
      params: { threadId: 'thread-1', turn: { id: 'turn-1', status: 'interrupted' } },
    });
    expect((await result).status).toBe('interrupted');
    expect(h.frames.find((f) => f.method === 'turn/interrupt')!.params).toEqual({
      threadId: 'thread-1',
      turnId: 'turn-1',
    });
  });

  it('fails pending work on process exit without inventing success', async () => {
    const h = harness();
    await h.client.start();
    const turn = h.client.runTurn('thread-1', 'Hello', { model: 'gpt-6-astra' });
    h.child.emit('exit', 1, null);
    await expect(turn).rejects.toThrow('offline');
    await expect(h.client.request('account/read')).rejects.toThrow('offline');
  });

  it('bounds RPC timeouts and rejects invalid/oversized protocol frames', async () => {
    const stalled = harness({ ignore: 'initialize' });
    await expect(stalled.client.start()).rejects.toThrow('timed out');
    const invalid = harness();
    await invalid.client.start();
    const offline: Error[] = [];
    invalid.client.on('offline', (error: Error) => offline.push(error));
    invalid.child.stdout.write('not json\n');
    expect(offline[0].message).toContain('Invalid');
    const large = harness();
    await large.client.start();
    large.child.stdout.write('x'.repeat(2_000_001));
    await expect(large.client.request('account/read')).rejects.toThrow('too large');
  });

  it('does not surface reasoning deltas as assistant content', async () => {
    const h = harness();
    await h.client.start();
    const deltas: string[] = [];
    h.client.on('notification', (notification: Notification) => {
      if (notification.method === 'item/agentMessage/delta') deltas.push(notification.params.delta);
    });
    h.send({
      method: 'item/reasoning/summaryTextDelta',
      params: { threadId: 'thread-1', delta: 'private' },
    });
    expect(deltas).toEqual([]);
  });
});
