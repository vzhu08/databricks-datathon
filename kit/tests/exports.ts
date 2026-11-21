/** Real external projects: no toolkit node_modules symlinks or workspace dependencies. */
import { mkdtemp, readFile, writeFile, mkdir, readdir, realpath } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { readCatalog, kitRoot } from '../tools/catalog';
import { planProject, applyPlan, materializeLock } from '../tools/project';
import { checkDocumentation } from '../tools/docs-check';
import { npmCommand } from '../tools/npm-command';
const root = await realpath(await mkdtemp(path.join(os.tmpdir(), 'kit-export-verification-')));
const catalog = await readCatalog();
const results: unknown[] = [];
console.log(`External verification directory: ${root}`);
function run(target: string, args: string[], repeatedSecurityReminder = false): string {
  try {
    const npm = npmCommand(args);
    return execFileSync(npm.file, npm.args, {
      cwd: target,
      encoding: 'utf8',
      timeout: 240_000,
      maxBuffer: 10_000_000,
      env: { ...process.env, NEXT_TELEMETRY_DISABLED: '1' },
    });
  } catch (e) {
    const error = e as { stdout?: string; stderr?: string };
    // Next's one-time advisory reminder exits after a completed build. Keep the
    // warning visible and retry the identical local check once; never hide a failure.
    if (
      !repeatedSecurityReminder &&
      args[0] === 'run' &&
      `${error.stderr ?? ''}`.includes('Error [SecurityFatalError]')
    ) {
      console.warn(
        'Existing Next.js security advisory: upgrade is recommended. Repeating the identical export check once.',
      );
      return run(target, args, true);
    }
    console.error(error.stdout, error.stderr);
    throw e;
  }
}
async function portable(directory: string) {
  for (const item of await readdir(directory, { withFileTypes: true })) {
    if (['node_modules', '.next', '.kit'].includes(item.name)) continue;
    assert(!item.isSymbolicLink(), `Exported symlink: ${item.name}`);
    const file = path.join(directory, item.name);
    if (item.isDirectory()) await portable(file);
    else if (/\.(?:json|ts|tsx|js|mjs)$/.test(item.name))
      assert(
        !(await readFile(file, 'utf8')).includes(kitRoot),
        `Source checkout leaked into ${file}`,
      );
  }
}
async function smoke(target: string, port: number, route: string, expected: string) {
  const child = spawn(
    process.execPath,
    ['node_modules/next/dist/bin/next', 'start', '--hostname', '127.0.0.1', '--port', String(port)],
    { cwd: target, stdio: 'ignore', env: { ...process.env, NEXT_TELEMETRY_DISABLED: '1' } },
  );
  try {
    let ready = false;
    for (let i = 0; i < 80; i++) {
      try {
        const r = await fetch(`http://127.0.0.1:${port}/api/health`);
        if (r.ok) {
          ready = true;
          break;
        }
      } catch {}
      await new Promise((r) => setTimeout(r, 100));
    }
    assert(ready, 'Exported server did not become ready');
    const response = await fetch(`http://127.0.0.1:${port}${route}`);
    assert.equal(response.status, 200);
    assert((await response.text()).includes(expected));
    const transform = await fetch(`http://127.0.0.1:${port}/api/transform`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text: '  exported    project  ' }),
    });
    assert.equal(transform.status, 200);
    assert.equal((await transform.json()).text, 'exported project');
  } finally {
    child.kill('SIGTERM');
    await new Promise<void>((r) => {
      if (child.exitCode !== null) r();
      else {
        child.once('exit', () => r());
        setTimeout(() => {
          child.kill('SIGKILL');
          r();
        }, 3000).unref();
      }
    });
  }
}
try {
  const requested = process.argv
    .find((a) => a.startsWith('--recipes='))
    ?.slice(10)
    .split(',');
  const recipes =
    requested ??
    (process.argv.includes('--quick')
      ? ['web']
      : ['web', 'document-python', 'group', 'media', 'full']);
  for (const [index, starter] of recipes.entries()) {
    const target = path.join(root, starter);
    console.log(`${starter}: generate snapshot and prune exact lock`);
    const plan = await planProject({
      target,
      operation: 'create',
      starter,
      ids: starter === 'full' ? catalog.map((m) => m.id) : [],
      catalog,
    });
    assert.deepEqual(plan.conflicts, []);
    await applyPlan(plan);
    await materializeLock(plan);
    await portable(target);
    const pkg = JSON.parse(await readFile(path.join(target, 'package.json'), 'utf8'));
    const lock = JSON.parse(await readFile(path.join(target, 'package-lock.json'), 'utf8'));
    if (starter === 'web') {
      assert.deepEqual(Object.keys(pkg.dependencies).sort(), ['next', 'react', 'react-dom', 'zod']);
      for (const name of ['ai', 'mammoth', '@supabase/supabase-js', 'ws'])
        assert(!lock.packages[`node_modules/${name}`], `Unused dependency in base lock: ${name}`);
    }
    const docs = await checkDocumentation(target);
    assert.deepEqual(docs.failures, [], 'Generated links must be self-contained');
    console.log(`${starter}: clean npm ci; typecheck, tests, production build`);
    run(target, ['ci', '--no-audit', '--no-fund']);
    run(target, ['run', 'check']);
    await smoke(
      target,
      3910 + index,
      starter === 'web' ? '/' : '/kit',
      starter === 'full'
        ? 'Capability studio'
        : starter === 'web'
          ? 'Less setup'
          : starter === 'group'
            ? 'everyone'
            : starter === 'media'
              ? 'bring an idea'
              : 'understanding',
    );
    results.push({
      starter,
      modules: plan.modules,
      dependencyEntries: Object.keys(lock.packages).length,
      status: 'passed',
    });
    console.log(`${starter}: PASS`);
    if (starter === 'web') {
      console.log(
        'existing app: preserve custom routes/instructions; adopt recommendations and rebuild',
      );
      await writeFile(
        path.join(target, 'app/page.tsx'),
        'export default function Page(){return <h1>Existing application preserved</h1>;}\n',
      );
      const owned = '# User-owned instructions\n';
      await writeFile(path.join(target, 'AGENTS.md'), owned);
      await mkdir(path.join(target, 'app/existing'), { recursive: true });
      await writeFile(
        path.join(target, 'app/existing/page.tsx'),
        'export default function Page(){return <h1>Existing second route</h1>;}\n',
      );
      const adoption = await planProject({
        target,
        ids: ['recommendations'],
        operation: 'add',
        catalog,
      });
      assert.deepEqual(adoption.conflicts, []);
      await applyPlan(adoption);
      assert.equal(await readFile(path.join(target, 'AGENTS.md'), 'utf8'), owned);
      const repeat = await planProject({
        target,
        ids: ['recommendations'],
        operation: 'add',
        catalog,
      });
      assert(repeat.changes.every((c) => c.action === 'unchanged'));
      run(target, ['install', '--no-audit', '--no-fund']);
      run(target, ['run', 'check']);
      await smoke(target, 3920, '/existing', 'Existing second route');
      results.push({
        adoption: 'Next App Router npm',
        preserved: ['custom home', 'second route', 'AGENTS.md'],
        status: 'passed',
      });
    }
  }
} finally {
  await mkdir(path.join(kitRoot, '.kit/verification'), { recursive: true });
  await writeFile(
    path.join(kitRoot, '.kit/verification/exports.json'),
    JSON.stringify(
      { root, results, verifiedAt: new Date().toISOString(), retainedForInspection: true },
      null,
      2,
    ) + '\n',
  );
  console.log(JSON.stringify({ root, results }, null, 2));
}
