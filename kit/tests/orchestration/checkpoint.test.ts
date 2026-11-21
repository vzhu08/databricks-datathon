import { describe, expect, it } from 'vitest';
import { ConfigSchema, TaskSchema, type RunState } from '../../tools/agents/contracts';
import { buildCheckpoint, redactTeamText, validateCheckpoint } from '../../tools/agents/checkpoint';
import { ContextUpdateSchema, SharedContextSchema } from '../../tools/agents/handoff-contracts';

const at = '2026-10-24T12:00:00Z';
const config = ConfigSchema.parse({
  schemaVersion: 1,
  runId: 'portable',
  repo: 'team/project',
  coordinator: 'lead',
  authorizedActors: ['lead'],
  workers: [{ name: 'a', githubLogin: 'alice' }],
  startedAt: at,
  deadline: '2026-10-25T12:00:00Z',
  checks: [{ id: 'test', command: 'node', args: ['--test'] }],
});
function state(): RunState {
  return {
    schemaVersion: 1,
    runId: config.runId,
    paused: false,
    tasks: [
      TaskSchema.parse({
        id: 'T1',
        runId: config.runId,
        version: 1,
        planVersion: 1,
        title: 'Fixture',
        description: 'Authored task',
        baseSha: 'a'.repeat(40),
        allowedPaths: ['src'],
        acceptance: ['Run fixture checks'],
        checkIds: ['test'],
        updatedAt: at,
      }),
    ],
    events: [],
    seenReports: [],
    notices: [],
    lastStatusAt: Date.parse(at),
    threadId: 'native-private-thread',
    context: SharedContextSchema.parse({
      summary: 'Portable project facts',
      requirements: ['Preserve source offsets'],
    }),
  };
}
describe('portable context integrity and privacy', () => {
  it('excludes native thread state and retains bounded sequenced history', () => {
    const value = state();
    value.events = Array.from({ length: 500 }, (_, i) => ({
      seq: i + 1,
      type: 'checkpoint',
      at,
      message: `Evidence ${i + 1}`,
    }));
    const checkpoint = buildCheckpoint(value, config, 'lead', at);
    expect(checkpoint.state.events).toHaveLength(200);
    expect(checkpoint.state.eventBaseSeq).toBe(300);
    expect(JSON.stringify(checkpoint)).not.toContain('native-private-thread');
    expect(() =>
      validateCheckpoint({ ...checkpoint, authentication: { token: 'do-not-share' } }, config),
    ).toThrow();
    expect(() =>
      validateCheckpoint(
        { ...checkpoint, state: { ...checkpoint.state, threadId: 'foreign-id' } },
        config,
      ),
    ).toThrow();
  });
  it('scrubs known credential patterns and refuses sensitive checkpoint data', () => {
    const secret = 'ghp_' + 'a'.repeat(35);
    const text = redactTeamText(`Use ${secret} with PRIVATE_API_KEY=abcdef123456 user@example.com`);
    expect(text).not.toContain(secret);
    expect(text).not.toContain('abcdef123456');
    expect(text).not.toContain('user@example.com');
    const value = state();
    value.tasks[0].description = `Secret ${secret}`;
    expect(() => buildCheckpoint(value, config, 'lead', at)).toThrow('Sensitive content');
  });
  it('rejects policy mismatch, stale approvals, bad dependencies and unauthorized rationale', () => {
    const checkpoint = buildCheckpoint(state(), config, 'lead', at);
    expect(() => validateCheckpoint({ ...checkpoint, actor: 'outsider' }, config)).toThrow('actor');
    expect(() =>
      validateCheckpoint({ ...checkpoint, policyDigest: 'b'.repeat(64) }, config),
    ).toThrow('policy');
    const broken = structuredClone(checkpoint);
    broken.state.tasks[0].dependencies = ['absent'];
    expect(() => validateCheckpoint(broken, config)).toThrow('dependency');
    const forged = structuredClone(checkpoint);
    forged.context.decisions.push({
      id: 'D1',
      actor: 'outsider',
      at,
      kind: 'architecture',
      summary: 'Untrusted',
      rationale: 'Not authorized',
    });
    expect(() => validateCheckpoint(forged, config)).toThrow('unauthorized');
    const stale = structuredClone(checkpoint);
    stale.state.approvedVersion = 3;
    expect(() => validateCheckpoint(stale, config)).toThrow('no plan');
  });
  it('bounds checkpoint bytes and keeps omitted context-update fields unchanged', () => {
    expect(ContextUpdateSchema.parse({ summary: 'New summary' })).toEqual({
      summary: 'New summary',
    });
    const value = state();
    value.context!.decisions = Array.from({ length: 300 }, (_, i) => ({
      id: `D-${i}`,
      at,
      actor: 'lead',
      kind: 'architecture' as const,
      summary: 'Choice',
      rationale: 'x'.repeat(4000),
    }));
    expect(() => buildCheckpoint(value, config, 'lead', at)).toThrow('1 MB');
  });
});
