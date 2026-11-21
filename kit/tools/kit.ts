#!/usr/bin/env node
import { parseArgs } from 'node:util';
import { spawnSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { buildCatalog, dependencyClosure, readCatalog } from './catalog';
import { applyPlan, materializeLock, planProject, printablePlan } from './project';
import { doctor } from './doctor';
import { planAgentsInstall, applyAgentsInstall } from './agents/install';
import { npmCommand } from './npm-command';

async function main() {
  const { positionals, values } = parseArgs({
    allowPositionals: true,
    options: {
      target: { type: 'string' },
      modules: { type: 'string' },
      starter: { type: 'string' },
      apply: { type: 'boolean' },
      json: { type: 'boolean' },
      port: { type: 'string' },
      help: { type: 'boolean' },
    },
  });
  const [command, arg] = positionals;
  const print = (value: unknown) =>
    console.log(typeof value === 'string' ? value : JSON.stringify(value, null, 2));
  if (!command || values.help) {
    print(
      'kit list | search <query> | inspect <id> | plan --target <path> --modules <ids> | create <path> [--starter web|document|group|media|full] [--modules <ids>] | add --target <path> --modules <ids> [--apply] | doctor [--target <path>] [--port <port>] | verify [--target <path>] | catalog build|check\nNo command initiates paid APIs or deploys. add and plan are read-only unless add --apply.',
    );
    return;
  }
  if (command === 'catalog') {
    if (!['build', 'check'].includes(arg)) throw new Error('Use catalog build or catalog check');
    const modules = await buildCatalog(arg === 'check');
    print({ status: 'pass', modules: modules.length, action: arg });
    return;
  }
  if (command === 'agents') {
    if (arg !== 'add' || !values.target)
      throw new Error('Use kit agents add --target <existing npm app> [--apply]');
    const plan = await planAgentsInstall(values.target);
    print({
      target: plan.target,
      changes: plan.changes,
      conflicts: plan.conflicts,
      instructions: plan.instructions,
    });
    if (values.apply) {
      await applyAgentsInstall(plan);
      print({ applied: true, target: plan.target });
    }
    if (plan.conflicts.length) process.exitCode = 2;
    return;
  }
  const catalog = await readCatalog();
  if (command === 'list' || command === 'search') {
    const q = positionals.slice(1).join(' ').toLowerCase();
    const matches = catalog.filter(
      (m) =>
        command === 'list' ||
        `${m.id} ${m.title} ${m.description} ${m.tags.join(' ')} ${m.useCases.join(' ')}`
          .toLowerCase()
          .includes(q),
    );
    print(
      values.json
        ? matches
        : matches.map((m) => `${m.id.padEnd(18)} ${m.description}`).join('\n') ||
            'No matches. Run kit list.',
    );
    return;
  }
  if (command === 'inspect') {
    const m = catalog.find((m) => m.id === arg);
    if (!m) throw new Error(`Unknown module ${arg}`);
    print(m);
    return;
  }
  const ids = (values.modules ?? '').split(',').filter(Boolean);
  const target = path.resolve(values.target ?? (command === 'create' ? (arg ?? '') : '.'));
  if (['plan', 'create', 'add'].includes(command)) {
    if (command === 'create' && !arg) throw new Error('create requires a target directory');
    if (command !== 'create' && !values.target)
      throw new Error('Pass --target explicitly for adoption planning');
    const plan = await planProject({
      target,
      ids,
      starter: values.starter ?? 'web',
      operation: command === 'create' ? 'create' : 'add',
      catalog,
    });
    print(printablePlan(plan));
    if (command === 'create' || (command === 'add' && values.apply)) {
      await applyPlan(plan);
      await materializeLock(plan);
      print({
        applied: true,
        target,
        changed: plan.changes.filter((c) => c.action !== 'unchanged').length,
        next:
          command === 'create'
            ? 'Run npm ci and npm run check in target. The selected dependency lockfile is included.'
            : 'Run npm install in target, review the dependency diff, then run project/module checks.',
      });
    }
    if (plan.conflicts.length) process.exitCode = 2;
    return;
  }
  if (command === 'doctor') {
    let selected = ids;
    if (!selected.length) {
      const record = JSON.parse(
        await readFile(path.join(target, 'kit.project.json'), 'utf8').catch(() => '{}'),
      );
      selected = record.closure ?? [];
    }
    const report = await doctor(
      target,
      dependencyClosure(selected, catalog),
      values.port ? Number(values.port) : undefined,
    );
    print(report);
    if (!report.healthy) process.exitCode = 1;
    return;
  }
  if (command === 'verify') {
    const pkg = JSON.parse(await readFile(path.join(target, 'package.json'), 'utf8'));
    const checks =
      target === path.resolve('.') && pkg.name === 'hackathon-kit'
        ? ['check', 'test', 'build']
        : pkg.scripts?.check
          ? ['check']
          : ['typecheck', 'test', 'build'].filter((x) => pkg.scripts?.[x]);
    if (!checks.length)
      throw new Error(
        'No supported verification scripts; run the selected module README checks manually.',
      );
    for (const script of checks) {
      const npm = npmCommand(['run', script]);
      const result = spawnSync(npm.file, npm.args, {
        cwd: target,
        stdio: 'inherit',
        env: { ...process.env, NEXT_TELEMETRY_DISABLED: '1' },
      });
      if (result.status !== 0) throw new Error(`Check failed: npm run ${script}`);
    }
    print({ verified: checks, live: 'not run' });
    return;
  }
  throw new Error(`Unknown command ${command}; run kit --help`);
}
main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
