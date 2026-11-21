import {
  readFile,
  readdir,
  lstat,
  realpath,
  mkdir,
  writeFile,
  rename,
  unlink,
} from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash, randomUUID } from 'node:crypto';
import { execFileSync } from 'node:child_process';

const sourceRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const hash = (b: Buffer) => createHash('sha256').update(b).digest('hex');
const read = (file: string) =>
  readFile(file).catch((e) => {
    if (e.code === 'ENOENT') return undefined;
    throw e;
  });
async function noLinks(root: string, relative = '') {
  let current = path.parse(root).root;
  for (const part of path
    .relative(current, root)
    .split(path.sep)
    .filter(Boolean)
    .concat(relative.split('/').filter(Boolean))) {
    current = path.join(current, part);
    const info = await lstat(current).catch((e) => {
      if (e.code !== 'ENOENT') throw e;
    });
    if (info?.isSymbolicLink())
      throw new Error(`Symlink/reparse point is not a valid installation path: ${current}`);
  }
}
export async function planAgentsInstall(targetInput: string) {
  const target = await realpath(path.resolve(targetInput));
  await noLinks(path.resolve(targetInput));
  if (target === sourceRoot || sourceRoot.startsWith(target + path.sep))
    throw new Error('Install into the application repository, not this kit or its parent');
  const files = new Map<string, Buffer>(),
    observed = new Map<string, Buffer | undefined>();
  const conflicts: string[] = [];
  const pkgPath = path.join(target, 'package.json'),
    pkgBytes = await readFile(pkgPath);
  const pkg = JSON.parse(pkgBytes.toString());
  if (pkg.type !== 'module')
    throw new Error(
      'Requires an npm project with type=module; review portable integration for other setups',
    );
  const rootPkg = JSON.parse(await readFile(path.join(sourceRoot, 'package.json'), 'utf8'));
  pkg.scripts ??= {};
  pkg.devDependencies ??= {};
  pkg.dependencies ??= {};
  const command = 'node --import tsx tools/agents/cli.ts';
  if (pkg.scripts.agents && pkg.scripts.agents !== command)
    conflicts.push('Existing scripts.agents differs; preserve and resolve manually');
  else pkg.scripts.agents = command;
  for (const [name, version] of Object.entries({
    zod: rootPkg.dependencies.zod,
    tsx: rootPkg.devDependencies.tsx,
  })) {
    const current = pkg.dependencies[name] ?? pkg.devDependencies[name];
    if (current && current !== version)
      conflicts.push(`${name}: existing ${current}, tested ${version}; review dependency conflict`);
    else if (!current) pkg.devDependencies[name] = version;
  }
  for (const entry of await readdir(path.join(sourceRoot, 'tools/agents'), {
    withFileTypes: true,
  })) {
    if (
      entry.isFile() &&
      (entry.name.endsWith('.ts') || ['README.md', 'LICENSE'].includes(entry.name))
    ) {
      const p = `tools/agents/${entry.name}`;
      files.set(p, await readFile(path.join(sourceRoot, p)));
    }
  }
  files.set(
    '.codex/agents/orchestrator.toml',
    await readFile(path.join(sourceRoot, '.codex/agents/orchestrator.toml')),
  );
  files.set(
    'docs/ORCHESTRATION.md',
    await readFile(path.join(sourceRoot, 'docs/guides/ORCHESTRATION.md')),
  );
  files.set('package.json', Buffer.from(JSON.stringify(pkg, null, 2) + '\n'));
  const ignore = (await read(path.join(target, '.gitignore')))?.toString() ?? '';
  files.set(
    '.gitignore',
    Buffer.from(
      ignore +
        (ignore.trimEnd().endsWith('\n.kit/') || ignore.trim() === '.kit/'
          ? ''
          : `${ignore.endsWith('\n') || !ignore ? '' : '\n'}.kit/\n`),
    ),
  );
  const recordName = 'orchestration.install.json';
  const oldBytes = await read(path.join(target, recordName));
  const old = oldBytes ? JSON.parse(oldBytes.toString()) : undefined;
  const changes: { path: string; action: string }[] = [];
  for (const [p, content] of files) {
    await noLinks(target, p);
    const previous = await read(path.join(target, p));
    observed.set(p, previous);
    const action = !previous ? 'create' : previous.equals(content) ? 'unchanged' : 'update';
    if (
      action === 'update' &&
      !['package.json', '.gitignore'].includes(p) &&
      old?.hashes?.[p] !== hash(previous!)
    )
      conflicts.push(`Preserve modified or user-owned ${p}; compare manually`);
    changes.push({ path: p, action });
  }
  let revision = 'unknown';
  try {
    revision = execFileSync('git', ['rev-parse', 'HEAD'], {
      cwd: sourceRoot,
      encoding: 'utf8',
    }).trim();
    if (
      execFileSync('git', ['status', '--porcelain'], { cwd: sourceRoot, encoding: 'utf8' }).trim()
    )
      revision += '-dirty';
  } catch {
    /* Source exports may lack Git metadata. */
  }
  files.set(
    recordName,
    Buffer.from(
      JSON.stringify(
        {
          schemaVersion: 1,
          sourceRevision: revision,
          hashes: Object.fromEntries([...files].map(([p, b]) => [p, hash(b)])),
        },
        null,
        2,
      ) + '\n',
    ),
  );
  observed.set(recordName, oldBytes);
  changes.push({ path: recordName, action: oldBytes ? 'update' : 'create' });
  return {
    target,
    files,
    observed,
    conflicts,
    changes,
    instructions: [
      'Review this file/dependency plan. No app routes or AGENTS.md/CLAUDE.md are changed.',
      'After --apply, run npm install, review package-lock.json, then npm run agents -- doctor.',
      'Configure GitHub identities/deadline with init, commit the add-on and config to your project; each laptop clones that project.',
    ],
  };
}
export async function applyAgentsInstall(plan: Awaited<ReturnType<typeof planAgentsInstall>>) {
  if (plan.conflicts.length) throw new Error(`Refusing installation: ${plan.conflicts.join('; ')}`);
  await noLinks(plan.target);
  for (const [p, expected] of plan.observed) {
    await noLinks(plan.target, p);
    const actual = await read(path.join(plan.target, p));
    if (expected ? !actual?.equals(expected) : actual !== undefined)
      throw new Error(`Target changed after planning: ${p}`);
  }
  const written: string[] = [];
  try {
    for (const [p, bytes] of plan.files) {
      if (plan.observed.get(p)?.equals(bytes)) continue;
      await noLinks(plan.target, p);
      const filename = path.join(plan.target, p),
        temp = `${filename}.${randomUUID()}.tmp`;
      await mkdir(path.dirname(filename), { recursive: true });
      try {
        await writeFile(temp, bytes, { flag: 'wx' });
        await rename(temp, filename);
        written.push(p);
      } finally {
        await unlink(temp).catch(() => {});
      }
    }
  } catch (e) {
    for (const p of written.reverse()) {
      await noLinks(plan.target, p);
      const old = plan.observed.get(p);
      if (old) await writeFile(path.join(plan.target, p), old);
      else await unlink(path.join(plan.target, p));
    }
    throw e;
  }
}
