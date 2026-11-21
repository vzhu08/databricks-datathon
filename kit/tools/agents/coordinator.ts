import { randomUUID } from 'node:crypto';
import {
  ConfigSchema,
  PlanSchema,
  TaskSchema,
  WorkerReportSchema,
  type Config,
  type Plan,
  type Task,
  type Event,
  type RunState,
  type QueueTransport,
  type ChatBridge,
} from './contracts';
import { StateStore } from './state';
import type { PrObservation } from './ci';
import {
  assertSharedSafe,
  buildCheckpoint,
  redactTeamText,
  validateCheckpoint,
} from './checkpoint';
import {
  ContextUpdateSchema,
  DecisionInputSchema,
  DecisionSchema,
  SharedContextSchema,
  SharedMessageSchema,
  coordinatorActors,
  type ContextUpdate,
  type DecisionInput,
  type SharedMessage,
} from './handoff-contracts';
import { pendingHandoff, respondHandoff } from './handoff-request';

const active = new Set(['Assigned', 'Running', 'Blocked', 'Paused']);
const terminal = new Set(['Verified', 'Failed', 'Cancelled']);
const sameTask = (a: Task, b: Task) =>
  JSON.stringify(TaskSchema.parse(a)) === JSON.stringify(TaskSchema.parse(b));
export function overlaps(a: string, b: string) {
  // Conservative across case-sensitive and case-insensitive team computers.
  a = a.toLowerCase();
  b = b.toLowerCase();
  return a === b || a.startsWith(b + '/') || b.startsWith(a + '/');
}
export function validatePlan(plan: Plan, config: Config) {
  PlanSchema.parse(plan);
  const byId = new Map(plan.tasks.map((t) => [t.id, t]));
  if (byId.size !== plan.tasks.length) throw new Error('Duplicate task IDs');
  const visiting = new Set<string>(),
    done = new Set<string>();
  const visit = (id: string) => {
    const task = byId.get(id);
    if (!task) throw new Error(`Missing dependency ${id}`);
    if (visiting.has(id)) throw new Error(`Dependency cycle at ${id}`);
    if (done.has(id)) return;
    visiting.add(id);
    task.dependencies.forEach(visit);
    visiting.delete(id);
    done.add(id);
  };
  for (const task of plan.tasks) {
    if (task.runId !== config.runId) throw new Error('Task run ID does not match configuration');
    if (task.checkIds.some((id) => !config.checks.some((c) => c.id === id)))
      throw new Error(`Unknown check ID in ${task.id}`);
    for (const p of task.allowedPaths) {
      if (config.reservedPaths.concat(task.reservedPaths).some((r) => overlaps(p, r)))
        throw new Error(`Reserved path in ${task.id}: ${p}; integration steward must handle it`);
      if (/(^|\/)(?:\.env[^/]*|\.git|\.kit|\.ssh|\.aws|node_modules)(\/|$)/i.test(p))
        throw new Error(`Protected path in ${task.id}`);
    }
    visit(task.id);
  }
}

export class Coordinator implements ChatBridge {
  readonly config: Config;
  private state: RunState;
  private listeners = new Set<(e: Event) => void>();
  private serial: Promise<unknown> = Promise.resolve();
  private online = false;
  private leadership = false;
  private lastPrPoll = 0;
  private root = '.';
  private restorePortable = false;
  private allowLocalOnly = false;
  private handoffGuard?: () => Promise<void | (() => void)>;
  private checkpointError?: string;
  private constructor(
    config: Config,
    private store: StateStore,
    private transport?: QueueTransport,
    private now: () => number = Date.now,
    private inspectPr?: (task: Task) => Promise<PrObservation>,
  ) {
    this.config = ConfigSchema.parse(config);
    this.state = {
      schemaVersion: 1,
      runId: config.runId,
      paused: false,
      tasks: [],
      events: [],
      seenReports: [],
      notices: [],
      lastStatusAt: now(),
    };
  }
  static async open(
    config: Config,
    root: string,
    options: {
      transport?: QueueTransport;
      now?: () => number;
      inspectPr?: (task: Task) => Promise<PrObservation>;
      resume?: boolean;
      takeover?: boolean;
      allowLocalOnly?: boolean;
    } = {},
  ) {
    const coordinator = new Coordinator(
      config,
      new StateStore(root, config.runId),
      options.transport,
      options.now,
      options.inspectPr,
    );
    const state = await coordinator.store.load();
    coordinator.root = root;
    coordinator.restorePortable = !!(options.resume || options.takeover);
    coordinator.allowLocalOnly = options.allowLocalOnly ?? false;
    if (state) {
      if (state.runId !== config.runId) throw new Error('Persisted run does not match');
      coordinator.state = state;
      if (state.plan) validatePlan(state.plan, config);
    }
    return coordinator;
  }
  private queue<T>(operation: () => Promise<T>): Promise<T> {
    const result = this.serial.then(operation);
    this.serial = result.catch(() => {});
    return result;
  }
  getState() {
    return structuredClone(this.state);
  }
  onEvent(listener: (e: Event) => void) {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }
  setHandoffGuard(guard: () => Promise<void | (() => void)>) {
    this.handoffGuard = guard;
    return () => {
      if (this.handoffGuard === guard) this.handoffGuard = undefined;
    };
  }
  private ensureActive() {
    if (!this.online || (this.state.leadership && this.state.leadership.phase !== 'active'))
      throw new Error(
        'This coordinator has no active dispatch authority; resume or take over on the designated computer',
      );
  }
  private actor() {
    return this.state.leadership?.coordinator ?? this.config.coordinator;
  }
  private portableState(authorizeTask?: string) {
    const visible = structuredClone(this.state);
    const privateDrafts = new Set(this.state.pendingAuthorizations ?? []);
    for (const task of visible.tasks) {
      if (!privateDrafts.has(task.id) || task.id === authorizeTask) continue;
      if (['Assigned', 'Running'].includes(task.state)) task.state = 'Planned';
      delete task.lease;
      delete task.assignedWorker;
      delete task.branch;
      delete task.assignmentDecisionId;
    }
    visible.pendingPublications = visible.pendingPublications?.filter(
      (id) => !privateDrafts.has(id) || id === authorizeTask,
    );
    return visible;
  }
  private async checkpoint(authorizeTask?: string) {
    try {
      await this.store.save(this.state);
      if (!this.online) return;
      if (this.transport && !this.transport.saveCheckpoint && !this.allowLocalOnly)
        throw new Error('This transport cannot persist portable checkpoints; dispatch is disabled');
      const checkpoint = buildCheckpoint(
        this.portableState(authorizeTask),
        this.config,
        this.actor(),
        new Date(this.now()).toISOString(),
      );
      if (this.transport?.saveCheckpoint)
        this.state.leadership = await this.transport.saveCheckpoint(checkpoint);
      if (authorizeTask)
        this.state.pendingAuthorizations = this.state.pendingAuthorizations?.filter(
          (id) => id !== authorizeTask,
        );
      this.state.checkpointSequence = checkpoint.sequence;
      this.checkpointError = undefined;
      await this.store.save(this.state);
    } catch (error) {
      this.checkpointError =
        'Shared checkpoint failed; no new assignment is permitted until persistence succeeds';
      this.state.paused = true;
      await this.store.save(this.state).catch(() => {});
      throw error;
    }
  }
  private async decide(input: DecisionInput) {
    this.ensureActive();
    const decision = DecisionSchema.parse({
      ...DecisionInputSchema.parse(input),
      id: `decision-${randomUUID()}`,
      at: new Date(this.now()).toISOString(),
      actor: this.actor(),
    });
    assertSharedSafe(decision);
    this.state.context ??= SharedContextSchema.parse({});
    if (this.state.context.decisions.length >= 300)
      throw new Error(
        'Decision journal full; explicitly compact/archive before dispatching more work',
      );
    this.state.context.decisions.push(decision);
    await this.checkpoint();
    return decision;
  }
  recordDecision(input: DecisionInput) {
    return this.queue(async () => {
      const decision = await this.decide(input);
      await this.event('decision-persisted', `${decision.summary} — ${decision.rationale}`);
      return { persisted: decision.id, checkpointSequence: this.state.checkpointSequence };
    });
  }
  updateContext(input: ContextUpdate) {
    return this.queue(async () => {
      this.ensureActive();
      const update = ContextUpdateSchema.parse(input);
      assertSharedSafe(update);
      this.state.context = SharedContextSchema.parse({ ...this.state.context, ...update });
      await this.checkpoint();
      return { checkpointSequence: this.state.checkpointSequence, shared: true };
    });
  }
  rememberMessage(input: SharedMessage) {
    return this.queue(async () => {
      this.ensureActive();
      const message = SharedMessageSchema.parse(input);
      assertSharedSafe(message);
      this.state.context ??= SharedContextSchema.parse({});
      const messages = this.state.context.recentMessages;
      const index = messages.findIndex((m) => m.id === message.id);
      if (index >= 0) messages[index] = message;
      else {
        if (messages.length >= 60) {
          const expired = messages.findIndex((m) => !['pending', 'uncertain'].includes(m.status));
          if (expired < 0)
            throw new Error(
              'Portable pending request capacity reached; resolve or summarize old requests',
            );
          messages.splice(expired, 1);
        }
        messages.push(message);
      }
      await this.checkpoint();
      return { remembered: message.id, checkpointSequence: this.state.checkpointSequence };
    });
  }
  private async event(type: string, message: string, task?: Task, committedOffer = false) {
    if (this.state.events.length >= 20_000)
      throw new Error('Run event capacity reached; archive run before continuing');
    const event: Event = {
      seq: (this.state.eventBaseSeq ?? 0) + this.state.events.length + 1,
      at: new Date(this.now()).toISOString(),
      type,
      message,
      ...(task
        ? { taskId: task.id, worker: task.assignedWorker, evidence: task.evidence.slice(-1) }
        : {}),
    };
    this.state.events.push(event);
    try {
      await this.checkpoint();
    } catch (error) {
      if (!committedOffer) throw error;
      event.message +=
        ' The shared offer is committed, but this computer could not save its final journal entry; inspect shared status.';
    }
    for (const listener of this.listeners) {
      try {
        listener(structuredClone(event));
      } catch {
        /* UI is not state authority. */
      }
    }
  }
  private async publish(task: Task, authorize = false) {
    this.state.pendingPublications ??= [];
    if (!this.state.pendingPublications.includes(task.id))
      this.state.pendingPublications.push(task.id);
    const isDraft = this.state.pendingAuthorizations?.includes(task.id);
    if (isDraft && (!authorize || this.state.paused || task.state !== 'Assigned')) {
      await this.checkpoint();
      return;
    }
    await this.checkpoint(isDraft ? task.id : undefined);
    if (this.transport) Object.assign(task, await this.transport.publishTask(task));
    this.state.pendingPublications = this.state.pendingPublications.filter((id) => id !== task.id);
    await this.checkpoint();
  }
  async start() {
    await this.store.lock();
    const previousLocal = structuredClone(this.state);
    try {
      if (this.transport) {
        await this.transport.acquireLeadership();
        this.leadership = true;
      }
      this.online = true;
      this.state.leadership = await this.transport?.getLeadership?.();
      const checkpoint = await this.transport?.loadCheckpoint?.();
      if (checkpoint) {
        const portable = validateCheckpoint(checkpoint, this.config);
        if (portable.sequence < (this.state.checkpointSequence ?? 0))
          throw new Error('Remote checkpoint regressed; reconcile before resuming');
        if (
          this.restorePortable ||
          portable.sequence > (this.state.checkpointSequence ?? 0) ||
          this.state.pendingAuthorizations?.length
        ) {
          if (previousLocal.events.length || previousLocal.plan || previousLocal.context)
            await this.store.retainLocalSnapshot(previousLocal);
          this.state = {
            schemaVersion: 1,
            runId: this.config.runId,
            ...structuredClone(portable.state),
            context: structuredClone(portable.context),
            checkpointSequence: portable.sequence,
            leadership: this.state.leadership,
            reconstructed: true,
          };
          if (this.state.plan) validatePlan(this.state.plan, this.config);
          await this.store.save(this.state);
        }
      } else if (this.restorePortable)
        throw new Error(
          'No valid shared checkpoint exists; the original coordinator must checkpoint the run before handoff/takeover',
        );
      // Published records recover assignments after a machine/local-state loss.
      const remote = (await this.transport?.listTasks()) ?? [];
      const intent = (task: Task) => {
        const { version: _version, issue: _issue, ...rest } = TaskSchema.parse(task);
        return JSON.stringify(rest);
      };
      for (const task of remote) {
        const local = this.state.tasks.find((t) => t.id === task.id);
        if (!local) this.state.tasks.push(TaskSchema.parse(task));
        else if (checkpoint) {
          // Only metadata/reachability may differ from the atomic task authority.
          if (task.lease?.token !== local.lease?.token || task.state !== local.state)
            throw new Error(
              'Authoritative task changed during recovery; retry after reconciling leadership',
            );
          Object.assign(local, task);
        } else if (task.version > local.version) {
          if (intent(task) !== intent(local))
            throw new Error(`Remote task ${task.id} is newer; reconcile manually`);
          Object.assign(local, task);
        }
      }
      this.state.pendingPublications ??= [];
      for (const local of this.state.tasks) {
        const published = remote.find((t) => t.id === local.id);
        if (
          (local.lease || local.issue) &&
          (!published || intent(local) !== intent(published)) &&
          !this.state.pendingPublications.includes(local.id)
        )
          this.state.pendingPublications.push(local.id);
      }
      if (remote.length && !this.state.plan) this.state.paused = true;
      await this.event(
        'coordinator-online',
        this.restorePortable
          ? `Leadership acquired at epoch ${this.state.leadership?.epoch}. Restored ${this.state.tasks.filter((t) => ['Assigned', 'Running'].includes(t.state)).length} active tasks, ${this.state.tasks.filter((t) => t.state === 'Verified').length} verified tasks and ${this.state.tasks.flatMap((t) => t.blockers.filter((b) => !b.resolved)).length} open blockers. Context reconstructed from the shared checkpoint; native account history stays local.`
          : 'Coordinator connected. Restored events are replay; new dispatch requires approved decisions saved in the shared checkpoint.',
      );
    } catch (error) {
      await this.close();
      throw error;
    }
  }
  async close() {
    this.online = false;
    try {
      if (this.leadership) await this.transport?.releaseLeadership();
    } finally {
      this.leadership = false;
      await this.store.unlock();
    }
  }
  handoff(successor: string) {
    return this.queue(() => this.performHandoff(successor));
  }
  private async performHandoff(successor: string) {
    this.ensureActive();
    if (!this.transport?.prepareHandoff)
      throw new Error('This transport has no durable leadership transfer support');
    const target =
      this.config.workers.find((worker) => worker.name === successor)?.githubLogin ?? successor;
    if (!coordinatorActors(this.config).includes(target.toLowerCase()))
      throw new Error('Successor is not an authorized configured teammate');
    if (target.toLowerCase() === this.actor().toLowerCase())
      throw new Error('This identity already coordinates; choose another teammate');
    const finishPreparation = await this.handoffGuard?.();
    try {
      await this.decide({
        kind: 'handoff',
        summary: `Prepare leadership transfer to ${target}`,
        rationale:
          'The current operator explicitly requested transfer. Existing worker assignments and approvals are preserved; new dispatch pauses until successor CAS acquisition.',
      });
      await this.event(
        'handoff-prepared',
        `Durable context ready for ${target}; existing workers continue.`,
      );
      const checkpoint = buildCheckpoint(
        this.portableState(),
        this.config,
        this.actor(),
        new Date(this.now()).toISOString(),
      );
      const leadership = await this.transport.prepareHandoff(target, checkpoint);
      this.state.leadership = leadership;
      this.state.checkpointSequence = checkpoint.sequence;
      this.online = false;
      this.leadership = false;
      await this.event(
        'handoff-offered',
        `Transfer offered to ${target}. Receipt requires that teammate to run npm run agents -- coordinate --resume; transfer is not complete until they acquire leadership.`,
        undefined,
        true,
      );
      return {
        status: 'offered',
        completed: false,
        successor: target,
        epoch: leadership.epoch,
        checkpointSequence: checkpoint.sequence,
        next: 'Receiving computer: npm run agents -- coordinate --resume',
      };
    } catch (error) {
      this.state.paused = true;
      this.online = false;
      this.leadership = false;
      await this.event(
        'leadership-lost',
        'Handoff outcome is not confirmed; this lead stopped dispatching. Inspect shared status before receiving/retrying. Worker scopes remain unchanged.',
      );
      throw error;
    } finally {
      if (typeof finishPreparation === 'function') finishPreparation();
    }
  }
  saveThread(id: string) {
    return this.queue(async () => {
      this.state.threadId = id;
      this.state.reconstructed = false;
      await this.store.save(this.state);
    });
  }
  propose(input: Plan) {
    return this.queue(async () => {
      this.ensureActive();
      const plan = PlanSchema.parse(input);
      if (!plan.rationale)
        throw new Error(
          'A new plan must include its rationale before any assignment can be approved',
        );
      assertSharedSafe(plan);
      validatePlan(plan, this.config);
      if (plan.version !== (this.state.plan?.version ?? 0) + 1)
        throw new Error('Plan version must increment by one');
      for (const task of this.state.tasks.filter(
        (t) => t.lease && !['Verified', 'Failed'].includes(t.state),
      )) {
        const proposed = plan.tasks.find((t) => t.id === task.id);
        if (!proposed || !sameTask(proposed, task))
          throw new Error(
            `Replan must preserve active task ${task.id} exactly; stop and confirm its worker before replacing scope`,
          );
      }
      for (const task of plan.tasks) {
        const old = this.state.tasks.find((t) => t.id === task.id);
        if (
          !old ||
          (!old.lease && !['Review', 'Queued', 'Merged'].includes(old.state)) ||
          terminal.has(old.state)
        ) {
          if (task.state !== 'Planned' && !(old && terminal.has(old.state) && sameTask(task, old)))
            throw new Error('New or edited tasks must start Planned');
          if (
            !old &&
            (task.lease ||
              task.assignedWorker ||
              task.issue ||
              task.pr ||
              task.evidence.length ||
              task.blockers.length)
          )
            throw new Error('New tasks cannot contain fabricated assignments or evidence');
          if (!old && task.planVersion !== plan.version)
            throw new Error('New task planVersion must match proposed plan');
          if (task.state === 'Planned') {
            task.sharedContract = plan.contract;
            task.planVersion = plan.version;
          }
        }
      }
      this.state.plan = plan;
      this.state.approvedVersion = undefined;
      this.state.tasks = structuredClone(plan.tasks);
      await this.decide({
        kind: 'plan',
        summary: plan.objective,
        rationale: plan.rationale,
        planVersion: plan.version,
      });
      await this.event(
        'approval-requested',
        `Plan ${plan.version} awaits human approval: ${plan.objective}`,
      );
      return { version: plan.version, approvalRequired: true };
    });
  }
  approve(version: number) {
    return this.queue(async () => {
      this.ensureActive();
      if (!this.state.plan || this.state.plan.version !== version)
        throw new Error('Approval version is stale');
      this.state.approvedVersion = version;
      await this.decide({
        kind: 'approval',
        summary: `Human approved plan ${version}`,
        rationale:
          'Explicit human approval of the recorded plan and its rationale; future dispatch remains constrained by ownership, dependencies and checks.',
        planVersion: version,
      });
      await this.event(
        'plan-approved',
        `Human approved plan ${version}; scoped task commits${this.config.allowPush ? ', pushes and draft PRs' : ' only; push disabled'}.`,
      );
      return { approved: version };
    });
  }
  reject(version: number) {
    return this.queue(async () => {
      this.ensureActive();
      if (this.state.plan?.version !== version) throw new Error('Rejection version is stale');
      this.state.approvedVersion = undefined;
      await this.event(
        'plan-rejected',
        `Plan ${version} rejected; active writers retain their previous scope.`,
      );
      return { rejected: version };
    });
  }
  action(action: 'pause' | 'resume' | 'cancel', taskId?: string) {
    return this.queue(async () => {
      this.ensureActive();
      await this.decide({
        kind: 'control',
        summary: `Human requested ${action}${taskId ? ` for ${taskId}` : ' for run'}`,
        rationale:
          'Explicit operator control command; existing scopes remain reserved until stopped-process confirmation.',
        taskId,
      });
      if (!taskId) {
        this.state.paused = action !== 'resume';
        if (action === 'cancel') this.state.approvedVersion = undefined;
      }
      const tasks = taskId
        ? this.state.tasks.filter((t) => t.id === taskId)
        : this.state.tasks.filter((t) => !terminal.has(t.state));
      if (taskId && !tasks.length) throw new Error('Unknown task');
      for (const task of tasks) {
        if (terminal.has(task.state)) continue;
        if (['Review', 'Queued', 'Merged'].includes(task.state) && !taskId) continue;
        if (action === 'resume') {
          if (task.state === 'Paused' && !task.lease) task.state = 'Planned';
          continue;
        }
        task.state = action === 'cancel' ? 'Cancelled' : 'Paused';
        task.updatedAt = new Date(this.now()).toISOString();
        await this.store.save(this.state);
        if (task.issue) await this.publish(task);
      }
      await this.event(
        `control-${action}`,
        `${action} recorded${taskId ? ` for ${taskId}` : ' for run'}; worker stop is requested, not confirmed. Existing leases remain reserved.`,
      );
      return { requested: action, workerStopConfirmed: false };
    });
  }
  confirmStopped(taskId: string) {
    return this.queue(async () => {
      this.ensureActive();
      const task = this.state.tasks.find((t) => t.id === taskId);
      if (!task || !task.lease) throw new Error('No leased task to release');
      if (task.state === 'Running' || task.state === 'Assigned')
        throw new Error(
          'Pause or cancel task first; then stop its worker process before confirming',
        );
      if (['Review', 'Queued', 'Merged', 'Verified'].includes(task.state))
        throw new Error('Review/integration scopes remain reserved until verified');
      await this.decide({
        kind: 'control',
        summary: `Release scope for ${taskId}`,
        rationale:
          'Human explicitly confirmed the old worker process stopped. Retained branches stay intact; a fresh task ID is required for another attempt.',
        taskId,
      });
      task.state = 'Failed';
      task.lease = undefined;
      await this.event(
        'scope-released',
        'Human confirmed old writer stopped; lease revoked. Branch retained. New approved task ID required to retry.',
        task,
      );
      if (task.issue) await this.publish(task);
      return { released: taskId, branchPreserved: task.branch };
    });
  }
  recordIntegrated(taskId: string, sha: string, summary: string) {
    return this.queue(async () => {
      this.ensureActive();
      const task = this.state.tasks.find((t) => t.id === taskId);
      if (!task || task.state !== 'Merged' || !/^[a-f0-9]{40}$/.test(sha))
        throw new Error(
          'Integrated verification requires a confirmed merged task and valid commit SHA',
        );
      const merged = [...task.evidence].reverse().find((e) => e.kind === 'merge');
      if (merged?.sha !== sha) throw new Error('Verification must use the confirmed merge commit');
      task.evidence.push({
        kind: 'integration',
        summary,
        sha,
        at: new Date(this.now()).toISOString(),
        exitCode: 0,
      });
      task.state = 'Verified';
      await this.event(
        'integrated-verified',
        'Integrated commit passed deterministic configured checks.',
        task,
      );
      await this.publish(task);
      return { verified: taskId, sha };
    });
  }
  resolve(taskId: string, blockerId: string, answer: string) {
    return this.queue(async () => {
      this.ensureActive();
      const task = this.state.tasks.find((t) => t.id === taskId);
      const blocker = task?.blockers.find((b) => b.id === blockerId);
      if (!task || !blocker || blocker.resolved) throw new Error('No unresolved matching blocker');
      if (!answer.trim() || answer.length > 2000)
        throw new Error('Answer must be 1–2000 characters');
      this.state.context ??= SharedContextSchema.parse({});
      if (this.state.context.answeredQuestions.length >= 40)
        throw new Error('Answered-question capacity reached; compact shared context explicitly');
      await this.decide({
        kind: 'clarification',
        summary: `Resolved ${taskId}/${blockerId}`,
        rationale: answer,
        taskId,
      });
      this.state.context.answeredQuestions.push({ question: blocker.question, answer });
      blocker.resolved = answer;
      await this.event(
        'blocker-resolved',
        `${blockerId} answered. A new task/approval is required if the stopped worker needs another implementation attempt.`,
        task,
      );
      if (task.issue) await this.publish(task);
      return { resolved: blockerId };
    });
  }
  status() {
    const visible = this.portableState();
    return {
      mode: this.transport
        ? 'live transport (evidence determines verification)'
        : 'offline simulation',
      runId: this.config.runId,
      objective: this.state.plan?.objective ?? 'No plan proposed',
      lead: this.online
        ? 'coordinator online; model turn state is separate'
        : 'coordinator offline',
      deadline: this.config.deadline,
      remainingMinutes: Math.floor((Date.parse(this.config.deadline) - this.now()) / 60_000),
      paused: this.state.paused,
      localUnpublishedAssignments: this.state.pendingAuthorizations?.length ?? 0,
      leadership: this.state.leadership,
      checkpoint: {
        sequence: this.state.checkpointSequence ?? 0,
        lastSuccessful: this.state.leadership?.checkpoint?.at,
        error: this.checkpointError,
      },
      context: {
        summary: this.state.context?.summary ?? '',
        decisions: this.state.context?.decisions.length ?? 0,
        pendingRequests:
          this.state.context?.recentMessages.filter((message) =>
            ['pending', 'uncertain'].includes(message.status),
          ).length ?? 0,
      },
      counts: Object.fromEntries(
        [
          'Planned',
          'Assigned',
          'Running',
          'Review',
          'Queued',
          'Merged',
          'Verified',
          'Blocked',
          'Paused',
          'Cancelled',
        ].map((state) => [state, visible.tasks.filter((task) => task.state === state).length]),
      ),
      approvedVersion: this.state.approvedVersion,
      nextCheckpoint:
        'Next dependency release, test evidence or human decision; no estimated completion time',
      workers: this.config.workers.map((w) => {
        const task = visible.tasks.find(
          (t) => t.assignedWorker === w.name && !terminal.has(t.state),
        );
        const last = [...this.state.events].reverse().find((e) => e.worker === w.name);
        return {
          id: w.name,
          task: task?.id,
          state: task?.state ?? 'Waiting',
          lastVerified: task?.evidence.at(-1),
          lastEventAt: last?.at,
          leaseReachable: !!task?.lease && Date.parse(task.lease.expiresAt) > this.now(),
        };
      }),
      tasks: visible.tasks.map((t) => ({
        id: t.id,
        state: t.state,
        verification: t.evidence.filter((e) =>
          ['check', 'ci', 'integration', 'deployment'].includes(e.kind),
        ),
      })),
      blockers: visible.tasks.flatMap((t) =>
        t.blockers.filter((b) => !b.resolved).map((b) => ({ task: t.id, ...b })),
      ),
    };
  }
  tick() {
    return this.queue(async () => {
      if (!this.online) throw new Error('Coordinator must start before polling');
      try {
        await this.transport?.renewLeadership();
        this.state.leadership = await this.transport?.getLeadership?.();
      } catch (e) {
        this.state.paused = true;
        this.online = false;
        this.leadership = false;
        await this.event(
          'leadership-lost',
          'Leadership cannot be confirmed; dispatch stopped. Stop/recover explicitly.',
        );
        throw e;
      }
      const request = await pendingHandoff(this.root, this.config.runId);
      if (request) {
        try {
          if (
            request.runId !== this.config.runId ||
            request.actor.toLowerCase() !== this.actor().toLowerCase() ||
            this.now() - request.at > 120_000
          )
            throw new Error('Stale or unauthorized local handoff request');
          await this.performHandoff(request.to);
          await respondHandoff(
            this.root,
            this.config.runId,
            request,
            'offered',
            'Checkpoint saved and successor designated; receiving operator must acquire leadership to complete transfer.',
          );
          return;
        } catch (error) {
          await respondHandoff(
            this.root,
            this.config.runId,
            request,
            'rejected',
            redactTeamText(error instanceof Error ? error.message : 'Handoff failed', 4000),
          );
          if (!this.online) throw error;
        }
      }
      for (const id of [...(this.state.pendingPublications ?? [])]) {
        const task = this.state.tasks.find((t) => t.id === id);
        if (!task) throw new Error(`Pending publication has unknown task ${id}`);
        if (this.state.paused && this.state.pendingAuthorizations?.includes(id)) continue;
        await this.publish(task, true);
      }
      for (const input of (await this.transport?.listReports()) ?? []) {
        const report = WorkerReportSchema.parse(input);
        if (this.state.seenReports.includes(report.reportId)) continue;
        const task = this.state.tasks.find((t) => t.id === report.taskId);
        if (
          !task ||
          report.runId !== this.config.runId ||
          report.worker !== task.assignedWorker ||
          report.version > task.version ||
          report.leaseToken !== task.lease?.token
        )
          continue;
        if (this.state.seenReports.length >= 20_000)
          throw new Error('Report capacity reached; archive run');
        this.state.seenReports.push(report.reportId);
        const validAt = Date.parse(report.at);
        if (
          validAt > this.now() + 30_000 ||
          validAt < Date.parse(task.updatedAt) - this.config.leaseMs
        )
          continue;
        if (
          report.kind === 'heartbeat' &&
          task.lease &&
          active.has(task.state) &&
          validAt + this.config.leaseMs > this.now()
        ) {
          task.lease.expiresAt = new Date(validAt + this.config.leaseMs).toISOString();
          // Persisted reachability is deliberately not a code-progress event.
          await this.store.save(this.state);
          continue;
        }
        if (report.kind === 'stopped') {
          await this.event(
            'worker-stopped',
            'Worker process stop confirmed. Scope stays reserved until an explicit reviewed replan.',
            task,
          );
          continue;
        }
        if (!['Assigned', 'Running'].includes(task.state)) continue;
        if (report.kind === 'started') task.state = 'Running';
        if (report.kind === 'result') {
          if (!report.evidence.some((e) => e.kind === 'check' && e.exitCode === 0))
            throw new Error('Worker result lacks check evidence');
          task.state = 'Review';
          task.pr = report.pr;
        }
        if (report.kind === 'blocked') {
          if (!report.blocker) throw new Error('Blocked report missing actionable question');
          task.state = 'Blocked';
          if (!task.blockers.some((b) => b.id === report.blocker!.id))
            task.blockers.push(report.blocker);
        }
        task.evidence.push(...report.evidence);
        task.updatedAt = new Date(this.now()).toISOString();
        await this.event(
          `worker-${report.kind}`,
          report.blocker?.question ?? `${report.worker}/${task.id}: ${report.kind}`,
          task,
        );
        if (task.issue) await this.publish(task);
      }
      for (const task of this.state.tasks.filter(
        (t) => active.has(t.state) && t.lease && Date.parse(t.lease.expiresAt) <= this.now(),
      )) {
        const notice = `lost-${task.id}-${task.lease!.token}`;
        if (!this.state.notices.includes(notice)) {
          this.state.notices.push(notice);
          await this.event(
            'worker-unreachable',
            'Lease expired. Progress unknown; scope retained. Confirm old process stopped before any replacement.',
            task,
          );
        }
      }
      if (this.inspectPr && this.now() - this.lastPrPoll >= 60_000) {
        this.lastPrPoll = this.now();
        for (const task of this.state.tasks.filter(
          (t) => t.pr && ['Review', 'Queued', 'Merged'].includes(t.state),
        )) {
          const observation = await this.inspectPr(task);
          const summary = `${observation.ci}: ${observation.summary}`;
          if ([...task.evidence].reverse().find((e) => e.kind === 'ci')?.summary !== summary) {
            task.evidence.push({
              kind: 'ci',
              summary,
              url: observation.url,
              sha: observation.headSha,
              at: new Date(this.now()).toISOString(),
            });
            await this.event('ci-change', summary, task);
          }
          if (observation.ci === 'passed' && task.state === 'Review') task.state = 'Queued';
          if (observation.ci !== 'passed' && task.state === 'Queued') task.state = 'Review';
          if (observation.mergedSha && task.state !== 'Merged') {
            task.state = 'Merged';
            task.evidence.push({
              kind: 'merge',
              summary: 'GitHub confirmed human merge; integrated verification still required',
              sha: observation.mergedSha,
              url: observation.url,
              at: new Date(this.now()).toISOString(),
            });
            await this.event(
              'merge-confirmed',
              'Merged on GitHub; integrated checks pending.',
              task,
            );
          }
          await this.publish(task);
        }
      }
      if (
        this.state.plan &&
        this.state.approvedVersion === this.state.plan.version &&
        !this.state.paused &&
        this.now() < Date.parse(this.config.deadline)
      ) {
        if (
          !this.state.context?.decisions.some(
            (decision) =>
              decision.kind === 'plan' && decision.planVersion === this.state.plan?.version,
          )
        )
          throw new Error(
            'The approved plan has no persisted rationale; record/replan the legacy decision before new assignments',
          );
        for (const task of this.state.tasks) {
          if (!['Planned', 'Ready'].includes(task.state) || task.lease) continue;
          if (
            !task.dependencies.every((id) =>
              this.state.tasks.some((t) => t.id === id && t.state === 'Verified'),
            )
          )
            continue;
          const dependencyShas = task.dependencies
            .map((id) => this.state.tasks.find((t) => t.id === id)!)
            .map(
              (dependency) =>
                [...dependency.evidence].reverse().find((e) => e.kind === 'integration')?.sha,
            )
            .filter(Boolean);
          const staleBase = dependencyShas.length && !dependencyShas.includes(task.baseSha);
          const frozenFeature =
            task.category === 'feature' &&
            Date.parse(this.config.deadline) - this.now() <= 3 * 3_600_000;
          if (staleBase || frozenFeature) {
            task.state = 'Blocked';
            task.blockers.push({
              id: `${staleBase ? 'base' : 'freeze'}-${task.id}`.slice(0, 64),
              question: staleBase
                ? 'Task base predates verified dependencies. Propose a new plan with an integrated base SHA.'
                : 'Feature freeze is active. Cut this feature or replan only essential fixes/demo verification.',
              recommendation: staleBase
                ? 'Use the current integrated commit containing all dependencies; get plan approval again.'
                : 'Protect the final three hours for integration, fixes and rehearsal.',
              options: staleBase
                ? ['Replan with integrated base', 'Defer task']
                : ['Defer feature', 'Replan essential fix'],
              attempted: [],
              impact: 'No worker started; independent eligible work continues.',
            });
            await this.event('replan-required', task.blockers.at(-1)!.question, task);
            continue;
          }
          const conflicts = this.state.tasks.filter(
            (t) => t.id !== task.id && t.lease && !['Verified', 'Failed'].includes(t.state),
          );
          if (
            conflicts.some((other) =>
              task.allowedPaths.some((p) => other.allowedPaths.some((q) => overlaps(p, q))),
            )
          )
            continue;
          const worker = this.config.workers.find(
            (w) =>
              !this.state.tasks.some(
                (t) =>
                  t.assignedWorker === w.name &&
                  t.lease &&
                  !['Review', 'Queued', 'Merged', 'Verified', 'Failed'].includes(t.state),
              ),
          );
          if (!worker) break;
          const decision = await this.decide({
            kind: 'dispatch',
            taskId: task.id,
            planVersion: this.state.plan.version,
            summary: `Assign ${task.id} to ${worker.name}`,
            rationale:
              `Approved plan ${this.state.plan.version}: ${this.state.plan.rationale ?? this.state.context!.decisions.find((d) => d.kind === 'plan' && d.planVersion === this.state.plan!.version)!.rationale}. Dependencies are integrated, the worker is free, and the exclusive scope has no conflicting owner.`.slice(
                0,
                4000,
              ),
          });
          task.assignmentDecisionId = decision.id;
          this.state.pendingAuthorizations ??= [];
          this.state.pendingAuthorizations.push(task.id);
          task.state = 'Assigned';
          task.assignedWorker = worker.name;
          task.lease = {
            token: randomUUID(),
            epoch: task.version,
            expiresAt: new Date(this.now() + this.config.leaseMs).toISOString(),
          };
          task.branch = `codex/${this.config.runId}/${task.id}`;
          task.updatedAt = new Date(this.now()).toISOString();
          await this.store.save(this.state);
          await this.publish(task, true);
          await this.event(
            'task-dispatched',
            `Assigned ${task.id} to ${worker.name}; awaiting process evidence.`,
            task,
          );
        }
      }
      const remaining = Date.parse(this.config.deadline) - this.now();
      const elapsed = this.now() - Date.parse(this.config.startedAt);
      for (const [minutes, met, description] of [
        [
          45,
          !!this.state.approvedVersion,
          'Approve a small judge-demo plan and stable shared contracts',
        ],
        [
          180,
          this.state.tasks.some((t) => t.state === 'Verified'),
          'Verify a real integrated end-to-end slice; cut noncritical scope',
        ],
      ] as const) {
        if (
          elapsed >= minutes * 60_000 &&
          !met &&
          !this.state.notices.includes(`milestone-${minutes}`)
        ) {
          this.state.notices.push(`milestone-${minutes}`);
          await this.event(
            'milestone-missed',
            `Baseline ${minutes}-minute checkpoint has no confirming evidence. ${description}.`,
          );
        }
      }
      for (const hours of [12, 6, 3, 1, 0]) {
        if (remaining <= hours * 3_600_000 && !this.state.notices.includes(`deadline-${hours}`)) {
          this.state.notices.push(`deadline-${hours}`);
          await this.event(
            'deadline-notice',
            `${hours}h threshold reached. ${hours <= 3 ? 'Freeze new features; protect integration, demo rehearsal and submission.' : 'Review critical demo path and propose nonessential scope cuts.'}`,
          );
        }
      }
      if (
        this.state.tasks.some((t) => active.has(t.state)) &&
        this.now() - this.state.lastStatusAt >= 300_000
      ) {
        this.state.lastStatusAt = this.now();
        await this.event('status', JSON.stringify(this.status()));
      }
      await this.store.save(this.state);
    });
  }
}
