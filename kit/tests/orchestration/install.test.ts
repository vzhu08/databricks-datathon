import { afterEach, describe, expect, it } from 'vitest';
import { mkdtemp, readFile, writeFile, mkdir, rm, symlink } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { planAgentsInstall, applyAgentsInstall } from '../../tools/agents/install';

const roots: string[] = [];
afterEach(async () => {
  for (const root of roots.splice(0)) await rm(root, { recursive: true, force: true });
});
async function fixture() {
  const root = await mkdtemp(path.join(os.tmpdir(), 'kit-orchestration-adopt-'));
  roots.push(root);
  await mkdir(path.join(root, 'app'));
  await writeFile(
    path.join(root, 'package.json'),
    JSON.stringify({
      name: 'oliver-existing-mvp',
      type: 'module',
      scripts: { dev: 'next dev', custom: 'node keep.js' },
      dependencies: { react: '19.3.0' },
    }),
  );
  await writeFile(
    path.join(root, 'app/page.tsx'),
    'export default function Page(){return "Oliver MVP"}',
  );
  await writeFile(path.join(root, 'AGENTS.md'), 'Oliver owns these instructions.');
  await writeFile(path.join(root, 'CLAUDE.md'), '@AGENTS.md');
  return root;
}
describe('optional adoption preserves an existing MVP', () => {
  it('plans without writing and applies only the reviewed addon, preserving routes, scripts and instructions', async () => {
    const root = await fixture(),
      before = await readFile(path.join(root, 'package.json'), 'utf8');
    const plan = await planAgentsInstall(root);
    expect(plan.conflicts).toEqual([]);
    expect(await readFile(path.join(root, 'package.json'), 'utf8')).toBe(before);
    expect(plan.changes.some((c) => c.path === 'app/page.tsx' || c.path === 'AGENTS.md')).toBe(
      false,
    );
    await applyAgentsInstall(plan);
    const pkg = JSON.parse(await readFile(path.join(root, 'package.json'), 'utf8'));
    expect(pkg.scripts).toMatchObject({
      dev: 'next dev',
      custom: 'node keep.js',
      agents: 'node --import tsx tools/agents/cli.ts',
    });
    expect(await readFile(path.join(root, 'app/page.tsx'), 'utf8')).toContain('Oliver MVP');
    expect(await readFile(path.join(root, 'AGENTS.md'), 'utf8')).toBe(
      'Oliver owns these instructions.',
    );
    expect(await readFile(path.join(root, 'CLAUDE.md'), 'utf8')).toBe('@AGENTS.md');
    expect(await readFile(path.join(root, 'tools/agents/LICENSE'), 'utf8')).toContain(
      'MIT License',
    );
    expect(await readFile(path.join(root, '.gitignore'), 'utf8')).toContain('.kit/');
    expect(
      (await planAgentsInstall(root)).changes
        .filter((c) => !['orchestration.install.json'].includes(c.path))
        .every((c) => c.action === 'unchanged'),
    ).toBe(true);
  });
  it('refuses downstream addon edits, dependency conflicts and existing agents scripts', async () => {
    const root = await fixture();
    await applyAgentsInstall(await planAgentsInstall(root));
    await writeFile(
      path.join(root, 'tools/agents/coordinator.ts'),
      '// local downstream modification',
    );
    const plan = await planAgentsInstall(root);
    expect(plan.conflicts.join()).toContain('coordinator.ts');
    await expect(applyAgentsInstall(plan)).rejects.toThrow('Refusing');
    const pkg = JSON.parse(await readFile(path.join(root, 'package.json'), 'utf8'));
    pkg.scripts.agents = 'node my-existing-agents.js';
    pkg.devDependencies.zod = '3.0.0';
    await writeFile(path.join(root, 'package.json'), JSON.stringify(pkg));
    expect((await planAgentsInstall(root)).conflicts.join()).toMatch(/scripts.agents/);
    expect((await planAgentsInstall(root)).conflicts.join()).toMatch(/zod/);
  });
  it('detects changes since planning before writing any addon file', async () => {
    const root = await fixture(),
      plan = await planAgentsInstall(root);
    await writeFile(path.join(root, 'package.json'), '{"type":"module","userChange":true}');
    await expect(applyAgentsInstall(plan)).rejects.toThrow('Target changed');
    await expect(readFile(path.join(root, 'tools/agents/cli.ts'))).rejects.toMatchObject({
      code: 'ENOENT',
    });
  });
  it('appends a final ignore rule after an existing private-state negation', async () => {
    const root = await fixture();
    await writeFile(path.join(root, '.gitignore'), '.kit/\n!.kit/\n');
    const plan = await planAgentsInstall(root);
    expect(plan.files.get('.gitignore')!.toString()).toBe('.kit/\n!.kit/\n.kit/\n');
  });
  it('rejects symlink installation destinations', async () => {
    const root = await fixture(),
      linkRoot = await fixture();
    await symlink(
      root,
      path.join(linkRoot, 'redirect'),
      process.platform === 'win32' ? 'junction' : 'dir',
    );
    await expect(planAgentsInstall(path.join(linkRoot, 'redirect'))).rejects.toThrow('Symlink');
  });
});
