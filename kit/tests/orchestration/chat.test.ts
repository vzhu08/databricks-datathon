import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { PassThrough } from 'node:stream';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  ConfigSchema,
  TaskSchema,
  type ChatBridge,
  type RunState,
  type Event,
} from '../../tools/agents/contracts';
import { runChat, loadLeadInstructions, type ConversationClient } from '../../tools/agents/chat';
import type { ServerRequest } from '../../tools/agents/app-server';
import { SharedContextSchema } from '../../tools/agents/handoff-contracts';

const roots: string[] = [];
afterEach(async () => {
  for (const root of roots.splice(0)) await rm(root, { recursive: true, force: true });
});
async function waitFor(condition: () => boolean) {
  for (let i = 0; i < 300; i++) {
    if (condition()) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  throw new Error('Condition did not arrive');
}
async function harness(prior?: Partial<RunState>) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'kit-chat-'));
  roots.push(root);
  await mkdir(path.join(root, '.codex/agents'), { recursive: true });
  await writeFile(
    path.join(root, '.codex/agents/orchestrator.toml'),
    'name = "orchestrator"\ndeveloper_instructions = """\nLead role.\n"""\n',
  );
  const config = ConfigSchema.parse({
    schemaVersion: 1,
    runId: 'run-1',
    repo: 'team/project',
    coordinator: 'lead',
    authorizedActors: ['lead'],
    workers: [{ name: 'agent-a', githubLogin: 'alice' }],
    startedAt: '2026-10-24T12:00:00Z',
    deadline: '2026-10-25T12:00:00Z',
    checks: [{ id: 'test', command: 'npm', args: ['test'] }],
  });
  const state: RunState = {
    schemaVersion: 1,
    runId: config.runId,
    paused: false,
    tasks: [],
    events: [],
    seenReports: [],
    notices: [],
    lastStatusAt: 0,
    ...prior,
  };
  state.context = SharedContextSchema.parse(state.context ?? {});
  let listener: (event: Event) => void = () => {};
  let handoffGuard: (() => Promise<void | (() => void)>) | undefined;
  const bridge: ChatBridge = {
    config,
    getState: () => state,
    saveThread: vi.fn(async (id) => {
      state.threadId = id;
    }),
    status: vi.fn(() => ({ runId: config.runId, actual: 'idle', workers: [] })),
    propose: vi.fn(async (plan) => {
      state.plan = plan;
      return { staged: plan.version, approvalRequired: true };
    }),
    approve: vi.fn(async (version) => {
      state.approvedVersion = version;
      return { approved: version };
    }),
    reject: vi.fn(async () => ({ rejected: true })),
    action: vi.fn(async () => ({ action: 'requested' })),
    resolve: vi.fn(async () => ({ resolved: true })),
    recordDecision: vi.fn(async (decision) => {
      const value = {
        ...decision,
        id: `decision-${state.context!.decisions.length + 1}`,
        at: new Date().toISOString(),
        actor: 'lead',
      };
      state.context!.decisions.push(value);
      return value;
    }),
    updateContext: vi.fn(async (update) => {
      state.context = SharedContextSchema.parse({ ...state.context, ...update });
      return state.context;
    }),
    rememberMessage: vi.fn(async (message) => {
      const index = state.context!.recentMessages.findIndex((item) => item.id === message.id);
      if (index === -1) state.context!.recentMessages.push(message);
      else state.context!.recentMessages[index] = message;
      return { remembered: message.id };
    }),
    setHandoffGuard: (callback) => {
      handoffGuard = callback;
      return () => {
        handoffGuard = undefined;
      };
    },
    handoff: vi.fn(async (successor) => {
      const cleanup = await handoffGuard?.();
      try {
        listener({
          seq: 1,
          at: new Date().toISOString(),
          type: 'handoff-offered',
          message: `Offered to ${successor}`,
        });
        return { offered: true, successor };
      } finally {
        cleanup?.();
      }
    }),
    tick: vi.fn(async () => {}),
    onEvent: (callback) => {
      listener = callback;
      return () => {
        listener = () => {};
      };
    },
  };
  const turns: {
    text: string;
    resolve: (status?: 'completed' | 'interrupted') => void;
    reject: (error: Error) => void;
  }[] = [];
  const client: ConversationClient = {
    start: vi.fn(async () => {}),
    startThread: vi.fn(async (options) => options.threadId ?? 'lead-thread'),
    runTurn: vi.fn(
      (_threadId, text, options) =>
        new Promise<{ id: string; status: 'completed' | 'interrupted'; text: string }>(
          (resolve, reject) => {
            options.onDelta?.('Astra says hello');
            turns.push({
              text,
              resolve: (status = 'completed') =>
                resolve({ id: `turn-${turns.length}`, text: 'Astra says hello', status }),
              reject,
            });
          },
        ),
    ),
    interrupt: vi.fn(async () => {
      turns.at(-1)?.resolve('interrupted');
    }),
    close: vi.fn(() => {
      turns.at(-1)?.reject(new Error('Client closed'));
    }),
  };
  const input = new PassThrough();
  const output = new PassThrough();
  let text = '';
  output.on('data', (data) => {
    text += data.toString();
  });
  const run = () => runChat(bridge, { root, client, input, output, pollMs: 10 });
  return {
    root,
    config,
    state,
    bridge,
    client,
    turns,
    input,
    run,
    text: () => text,
    emit: (event: Event) => listener(event),
    prepareHandoff: async () => handoffGuard?.(),
  };
}

describe('persistent conversational lead', () => {
  it('loads the shipped literal role and refuses unsupported template syntax', async () => {
    const h = await harness();
    expect(await loadLeadInstructions(h.root)).toBe('Lead role.');
    await writeFile(
      path.join(h.root, '.codex/agents/orchestrator.toml'),
      'developer_instructions = "bad"',
    );
    await expect(loadLeadInstructions(h.root)).rejects.toThrow('Unsupported');
  });

  it('accepts queued user input, status, approval and real events while model work runs', async () => {
    const h = await harness();
    const run = h.run();
    await waitFor(() => h.text().includes('Started lead thread'));
    h.input.write('Build MVP\n');
    await waitFor(() => h.turns.length === 1);
    h.input.write('Use PDF input\n/status\n/approve 2\n');
    await waitFor(() => h.text().includes('QUEUED LOCALLY') && h.state.approvedVersion === 2);
    expect(h.text()).toContain('"actual": "idle"');
    h.emit({
      seq: 1,
      at: new Date().toISOString(),
      type: 'test',
      worker: 'agent-a',
      taskId: 'T1',
      message: 'Tests passed',
      evidence: [
        {
          kind: 'check',
          summary: '1 passed',
          command: 'npm test',
          exitCode: 0,
          at: new Date().toISOString(),
        },
      ],
    });
    expect(h.text()).toContain('agent-a/T1: Tests passed [npm test]');
    expect(h.bridge.tick).toHaveBeenCalled();
    h.turns[0].resolve();
    await waitFor(() => h.turns.length === 2);
    expect(h.turns[1].text).toContain('Use PDF input');
    expect(h.turns[1].text).toContain('Current deterministic coordinator snapshot');
    h.turns[1].resolve();
    await waitFor(() => h.text().includes('Turn turn-2 completed'));
    h.input.write('/quit\n');
    await run;
    const saved = JSON.parse(
      await readFile(path.join(h.root, '.kit/orchestration/chat-run-1.json'), 'utf8'),
    );
    expect(saved.queue).toEqual([]);
    expect(saved.active).toBeUndefined();
  });

  it('lets model tools stage a validated plan but never grant dispatch approval', async () => {
    const h = await harness();
    const run = h.run();
    await waitFor(() => !!h.client.onServerRequest && h.state.threadId === 'lead-thread');
    const task = TaskSchema.parse({
      id: 'T1',
      runId: 'run-1',
      version: 1,
      planVersion: 1,
      title: 'Task',
      description: 'Implement one scoped feature',
      baseSha: 'a'.repeat(40),
      allowedPaths: ['src/feature.ts'],
      acceptance: ['Works'],
      checkIds: ['test'],
      updatedAt: new Date().toISOString(),
    });
    const result = await h.client.onServerRequest!({
      id: 1,
      method: 'item/tool/call',
      params: {
        threadId: 'lead-thread',
        tool: 'orchestration_propose_plan',
        arguments: {
          version: 1,
          objective: 'Demo',
          contract: 'Shared schema',
          rationale: 'Prioritize the smallest demo slice',
          tasks: [task],
        },
      },
    });
    expect(result).toMatchObject({ success: true });
    expect(h.bridge.propose).toHaveBeenCalledOnce();
    expect(h.bridge.approve).not.toHaveBeenCalled();
    const rejected = await h.client.onServerRequest!({
      id: 2,
      method: 'item/tool/call',
      params: { threadId: 'lead-thread', tool: 'orchestration_approve', arguments: { version: 1 } },
    });
    expect(rejected).toMatchObject({ success: false });
    expect(h.bridge.approve).not.toHaveBeenCalled();
    h.input.write('/approve 1\n');
    await waitFor(() => h.state.approvedVersion === 1);
    h.input.write('/quit\n');
    await run;
  });

  it('routes process approval and questions to human input with exact request IDs', async () => {
    const h = await harness();
    const run = h.run();
    await waitFor(() => h.text().includes('Started lead thread'));
    const approved = h.client.onServerRequest!({
      id: 'p1',
      method: 'item/commandExecution/requestApproval',
      params: { threadId: 'lead-thread', command: 'git status' },
    });
    await waitFor(() => h.text().includes('APPROVAL> Request p1'));
    h.input.write('/allow p1\n');
    expect(await approved).toEqual({ decision: 'accept' });
    const answered = h.client.onServerRequest!({
      id: 'q1',
      method: 'item/tool/requestUserInput',
      params: {
        threadId: 'lead-thread',
        questions: [
          {
            id: 'input',
            question: 'PDF or LaTeX?',
            options: [{ label: 'PDF' }, { label: 'LaTeX' }],
          },
        ],
      },
    });
    await waitFor(() => h.text().includes('q1/input'));
    h.input.write('/answer q1 input PDF\n');
    expect(await answered).toEqual({ answers: { input: { answers: ['PDF'] } } });
    expect(h.state.context!.answeredQuestions).toEqual([
      { question: 'PDF or LaTeX?', answer: 'PDF' },
    ]);
    expect(JSON.stringify(h.state.context)).not.toContain('q1');
    expect(JSON.stringify(h.state.context)).not.toContain('p1');
    h.input.write('/allow p1\n');
    await waitFor(() => h.text().includes('stale process approvals'));
    h.input.write('/quit\n');
    await run;
  });

  it('restores queued messages and pending coordinator decisions without replaying stale process approvals', async () => {
    const h = await harness({ threadId: 'existing-thread' });
    await mkdir(path.join(h.root, '.kit/orchestration'), { recursive: true });
    await writeFile(
      path.join(h.root, '.kit/orchestration/chat-run-1.json'),
      JSON.stringify({
        schemaVersion: 1,
        runId: 'run-1',
        queue: ['Still queued'],
        active: 'Uncertain previous send',
        requests: [{ id: 'stale', method: 'item/fileChange/requestApproval' }],
      }),
    );
    const run = h.run();
    await waitFor(() => h.turns.length === 1);
    expect(h.text()).toContain('delivery is uncertain');
    expect(h.text()).toContain('cannot be approved by stale ID');
    expect(h.client.startThread).toHaveBeenCalledWith(
      expect.objectContaining({ threadId: 'existing-thread', model: 'gpt-6-astra' }),
    );
    expect(h.turns[0].text).toContain('Still queued');
    expect(h.turns[0].text).not.toContain('Uncertain previous send');
    h.turns[0].resolve();
    h.input.write('/quit\n');
    await run;
  });

  it('keeps unsent inputs local after an offline model failure and never claims delivery', async () => {
    const h = await harness();
    const run = h.run();
    await waitFor(() => h.text().includes('Started lead thread'));
    h.input.write('First\n');
    await waitFor(() => h.turns.length === 1);
    h.input.write('Second\n');
    await waitFor(() => h.text().includes('QUEUED LOCALLY'));
    h.turns[0].reject(new Error('Quota exhausted'));
    await waitFor(() => h.text().includes('CHAT OFFLINE'));
    h.input.write('/status\n/quit\n');
    await run;
    const saved = JSON.parse(
      await readFile(path.join(h.root, '.kit/orchestration/chat-run-1.json'), 'utf8'),
    );
    expect(saved.queue).toEqual(['Second']);
    expect(saved.active).toBe('First');
    expect(h.turns).toHaveLength(1);
    expect(h.text()).toContain('No automatic model/account substitution');
  });

  it('bounds and validates requests, denies unknown tools, and rejects secret prompts', async () => {
    const h = await harness();
    const run = h.run();
    await waitFor(() => h.text().includes('Started lead thread'));
    const request: ServerRequest = {
      id: 'bad',
      method: 'item/tool/call',
      params: {
        threadId: 'lead-thread',
        tool: 'orchestration_propose_plan',
        arguments: { version: 1 },
      },
    };
    expect(await h.client.onServerRequest!(request)).toMatchObject({ success: false });
    await expect(
      h.client.onServerRequest!({ ...request, method: 'unknown/action' }),
    ).rejects.toThrow('Unsupported');
    await expect(
      h.client.onServerRequest!({
        id: 'secret',
        method: 'item/tool/requestUserInput',
        params: {
          threadId: 'lead-thread',
          questions: [{ id: 'key', question: 'Secret?', isSecret: true, options: null }],
        },
      }),
    ).rejects.toThrow('Configure secrets outside');
    h.input.write('/quit\n');
    await run;
  });

  it('does not overlap GitHub synchronization while a poll is pending', async () => {
    const h = await harness();
    let release!: () => void;
    h.bridge.tick = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          release = resolve;
        }),
    );
    const run = h.run();
    await waitFor(() => h.text().includes('Started lead thread'));
    await new Promise((resolve) => setTimeout(resolve, 40));
    expect(h.bridge.tick).toHaveBeenCalledOnce();
    release();
    h.input.write('/quit\n');
    await run;
  });

  it('checkpoints a short scrubbed request before starting a model turn', async () => {
    const h = await harness();
    const remember = h.bridge.rememberMessage!;
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    h.bridge.rememberMessage = vi.fn(async (message) => {
      if (message.status === 'pending') await gate;
      return remember(message);
    });
    const run = h.run();
    await waitFor(() => h.text().includes('Started lead thread'));
    h.input.write(`Build the demo for person@example.com. ${'details '.repeat(180)}\n`);
    await waitFor(() => vi.mocked(h.bridge.rememberMessage!).mock.calls.length > 0);
    expect(h.turns).toHaveLength(0);
    const saved = vi.mocked(h.bridge.rememberMessage!).mock.calls[0][0];
    expect(saved.text.length).toBeLessThanOrEqual(1000);
    expect(saved.text).not.toContain('person@example.com');
    expect(saved.status).toBe('pending');
    await expect(h.prepareHandoff()).rejects.toThrow('still being checkpointed');
    release();
    await waitFor(() => h.turns.length === 1);
    h.turns[0].resolve();
    await waitFor(() => h.state.context!.recentMessages[0].status === 'answered');
    h.input.write('/quit\n');
    await run;
    expect(h.text()).toContain('Short scrubbed project request excerpts');
    expect(JSON.stringify(h.state.context)).not.toContain('Astra says hello');
  });

  it('does not send a model turn when the shared request checkpoint fails', async () => {
    const h = await harness();
    h.bridge.rememberMessage = vi.fn(async () => {
      throw new Error('checkpoint CAS unavailable');
    });
    const run = h.run();
    await waitFor(() => h.text().includes('Started lead thread'));
    h.input.write('Build the next scoped task\n');
    await waitFor(() => h.text().includes('checkpoint CAS unavailable'));
    expect(h.turns).toHaveLength(0);
    h.input.write('/quit\n');
    await run;
    const local = JSON.parse(
      await readFile(path.join(h.root, '.kit/orchestration/chat-run-1.json'), 'utf8'),
    );
    expect(local.queue).toEqual(['Build the next scoped task']);
  });

  it('persists user-facing decision reasons and curated context through validated tools only', async () => {
    const h = await harness();
    const run = h.run();
    await waitFor(() => h.text().includes('Started lead thread'));
    const call = (tool: string, args: unknown) =>
      h.client.onServerRequest!({
        id: randomId(),
        method: 'item/tool/call',
        params: { threadId: 'lead-thread', tool, arguments: args },
      });
    expect(
      await call('orchestration_record_decision', {
        kind: 'architecture',
        summary: 'Reuse PDF extraction',
        rationale: 'It preserves the working MVP and shortens the critical demo path',
      }),
    ).toMatchObject({ success: true });
    expect(h.state.context!.decisions[0].rationale).toContain('critical demo path');
    expect(
      await call('orchestration_update_context', {
        summary: 'PDF first, authored fixtures; preserve current MVP',
        priorities: ['source-backed report'],
      }),
    ).toMatchObject({ success: true });
    expect(h.state.context!.summary).toContain('PDF first');
    expect(
      await call('orchestration_record_decision', {
        kind: 'architecture',
        summary: 'Credential',
        rationale: `Use ghp_${'A'.repeat(30)}`,
      }),
    ).toMatchObject({ success: false });
    expect(await call('orchestration_handoff', { to: 'agent-b' })).toMatchObject({
      success: false,
    });
    expect(h.bridge.handoff).not.toHaveBeenCalled();
    h.input.write('/quit\n');
    await run;
  });

  it('reconstructs a new local-account thread from shared facts without resuming a foreign native thread', async () => {
    const context = SharedContextSchema.parse({
      summary: 'Preserve the research MVP. PDF first.',
      answeredQuestions: [{ question: 'Input?', answer: 'PDF' }],
      recentMessages: [
        {
          id: 'prior-request',
          role: 'user',
          text: 'Already handled project request',
          at: new Date().toISOString(),
          status: 'answered',
        },
      ],
    });
    const h = await harness({ reconstructed: true, threadId: 'foreign-account-thread', context });
    await mkdir(path.join(h.root, '.kit/orchestration'), { recursive: true });
    await writeFile(
      path.join(h.root, '.kit/orchestration/chat-run-1.json'),
      JSON.stringify({
        schemaVersion: 1,
        runId: 'run-1',
        queue: ['Already handled project request'],
        queueMeta: [
          { id: '11111111-1111-4111-8111-111111111111', private: false, sharedId: 'prior-request' },
        ],
        requests: [],
      }),
    );
    const run = h.run();
    await waitFor(() => h.text().includes('Leadership acquired'));
    const options = vi.mocked(h.client.startThread).mock.calls[0][0];
    expect(options.threadId).toBeUndefined();
    expect(options.developerInstructions).toContain('Preserve the research MVP');
    expect(options.developerInstructions).toContain('"answer": "PDF"');
    expect(options.developerInstructions).not.toContain('foreign-account-thread');
    expect(h.text()).toContain(
      '0 workers recorded running, 0 assignments awaiting start, 0 verified tasks, 0 tasks awaiting review, 0 blocked tasks',
    );
    expect(h.text()).toContain('Native history was not copied');
    expect(h.turns).toHaveLength(0);
    expect(h.text()).toContain('not replayed into this reconstructed coordinator');
    h.input.write('/quit\n');
    await run;
    const local = JSON.parse(
      await readFile(path.join(h.root, '.kit/orchestration/chat-run-1.json'), 'utf8'),
    );
    expect(local.queue).toEqual([]);
    expect(local.uncertainInputs[0].text).toBe('Already handled project request');
  });

  it('requires a safe summary for private pending input and reports an offer without claiming completed transfer', async () => {
    const h = await harness();
    const run = h.run();
    await waitFor(() => h.text().includes('Started lead thread'));
    h.input.write('/private Unshared private project details\n');
    await waitFor(() => h.turns.length === 1);
    h.input.write('/handoff --to agent-b\n');
    await waitFor(() => h.text().includes('private pending/in-flight/uncertain'));
    expect(h.bridge.handoff).toHaveBeenCalledOnce();
    expect(h.text()).not.toContain('Transfer offered;');
    expect(JSON.stringify(h.state.context)).not.toContain('Unshared private project details');
    await expect(h.bridge.handoff!('agent-b')).rejects.toThrow('private pending');
    h.input.write(
      '/remember Continue the approved scoped PDF implementation\n/handoff --to agent-b\n',
    );
    await run;
    expect(h.bridge.handoff).toHaveBeenLastCalledWith('agent-b');
    expect(h.text()).toContain('not complete until the receiver');
    expect(h.text()).not.toContain('transferred successfully');
    expect(JSON.stringify(h.state.context)).not.toContain('Unshared private project details');
    expect(h.client.interrupt).toHaveBeenCalled();
    const local = JSON.parse(
      await readFile(path.join(h.root, '.kit/orchestration/chat-run-1.json'), 'utf8'),
    );
    expect(JSON.stringify(local)).toContain('Unshared private project details');
  });

  it('treats automatically detected credentials as private and never shares their value', async () => {
    const h = await harness();
    const run = h.run();
    await waitFor(() => h.text().includes('Started lead thread'));
    const credential = `ghp_${'B'.repeat(30)}`;
    h.input.write(`Use ${credential} locally\n`);
    await waitFor(() => h.turns.length === 1);
    expect(h.text()).toContain('Sensitive input was omitted');
    expect(JSON.stringify(h.state.context)).not.toContain(credential);
    h.input.write(`/remember ${credential}\n`);
    await waitFor(() => h.text().includes('Sensitive content cannot enter'));
    expect(h.state.context!.recentMessages).toEqual([]);
    h.turns[0].resolve();
    await waitFor(() => h.text().includes('Turn turn-1 completed'));
    h.input.write('/quit\n');
    await run;
  });

  it('keeps prompts and model-originated writes derived from a private turn out of team context', async () => {
    const h = await harness();
    const run = h.run();
    await waitFor(() => h.text().includes('Started lead thread'));
    h.input.write('/private Confidential demo discussion\n');
    await waitFor(() => h.turns.length === 1);
    const decision = await h.client.onServerRequest!({
      id: 'private-tool',
      method: 'item/tool/call',
      params: {
        threadId: 'lead-thread',
        tool: 'orchestration_record_decision',
        arguments: {
          kind: 'scope',
          summary: 'Confidential demo discussion',
          rationale: 'Private fact',
        },
      },
    });
    expect(decision).toMatchObject({ success: false });
    expect(h.bridge.recordDecision).not.toHaveBeenCalled();
    const question = h.client.onServerRequest!({
      id: 'private-question',
      method: 'item/tool/requestUserInput',
      params: {
        threadId: 'lead-thread',
        questions: [{ id: 'choice', question: 'Which confidential demo detail?', options: null }],
      },
    });
    await waitFor(() => h.text().includes('private-question/choice'));
    h.input.write('/answer private-question choice Keep it local\n');
    expect(await question).toEqual({ answers: { choice: { answers: ['Keep it local'] } } });
    expect(h.state.context!.recentMessages).toEqual([]);
    expect(h.state.context!.answeredQuestions).toEqual([]);
    h.turns[0].resolve();
    await waitFor(() => h.text().includes('Turn turn-1 completed'));
    h.input.write('/quit\n');
    await run;
  });

  it('retains inputs arriving during external handoff locally without transferring or launching them', async () => {
    const h = await harness();
    const run = h.run();
    await waitFor(() => h.text().includes('Started lead thread'));
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const external = (async () => {
      const cleanup = await h.prepareHandoff();
      try {
        await gate;
        h.emit({
          seq: 1,
          at: new Date().toISOString(),
          type: 'handoff-offered',
          message: 'Offered to bob',
        });
      } finally {
        cleanup?.();
      }
    })();
    await waitFor(() => h.text().includes('Preparing transfer'));
    h.input.write(
      '/private New private input during transfer\nNew project request during transfer\n',
    );
    await waitFor(() => h.text().includes('2 deferred input(s)'));
    expect(h.turns).toHaveLength(0);
    expect(h.state.context!.recentMessages).toEqual([]);
    release();
    await external;
    await run;
    const local = JSON.parse(
      await readFile(path.join(h.root, '.kit/orchestration/chat-run-1.json'), 'utf8'),
    );
    expect(local.deferredInputs.map((item: { text: string }) => item.text)).toEqual([
      '/private New private input during transfer',
      'New project request during transfer',
    ]);
    expect(h.text()).toContain('not included in this transfer');
  });

  it('thaws ordered deferred input after a failed external handoff without publishing private content', async () => {
    const h = await harness();
    const run = h.run();
    await waitFor(() => h.text().includes('Started lead thread'));
    const cleanup = await h.prepareHandoff();
    h.input.write('/private Deferred private follow-up\nDeferred project follow-up\n');
    await waitFor(() => h.text().includes('2 deferred input(s)'));
    cleanup?.();
    await waitFor(() => h.turns.length === 1);
    expect(h.turns[0].text).toContain('Deferred private follow-up');
    expect(
      h.state.context!.recentMessages.some((message) =>
        message.text.includes('Deferred private follow-up'),
      ),
    ).toBe(false);
    h.turns[0].resolve();
    await waitFor(() => h.turns.length === 2);
    expect(h.turns[1].text).toContain('Deferred project follow-up');
    expect(
      h.state.context!.recentMessages.some(
        (message) => message.text === 'Deferred project follow-up',
      ),
    ).toBe(true);
    h.turns[1].resolve();
    await waitFor(() => h.text().includes('Turn turn-2 completed'));
    h.input.write('/quit\n');
    await run;
  });
});

function randomId() {
  return Math.random().toString(36).slice(2);
}
