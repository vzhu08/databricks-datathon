import { it, expect } from 'vitest';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { kitRoot, readCatalog } from '../tools/catalog';
import { checkDocumentation } from '../tools/docs-check';
import { applyPlan, planProject } from '../tools/project';

it('exports linked human context into a minimal app and preserves customized context on adoption', async () => {
  const target = await mkdtemp(path.join(os.tmpdir(), 'kit-human-workflow-'));
  try {
    const catalog = await readCatalog();
    const plan = await planProject({ target, ids: [], operation: 'create', catalog });
    expect(plan.conflicts).toEqual([]);
    await applyPlan(plan);

    const workflowPath = path.join(target, 'docs/HUMAN_AI_TEAM_WORKFLOW.md');
    expect(await readFile(workflowPath, 'utf8')).toBe(
      await readFile(path.join(kitRoot, 'docs/templates/HUMAN_AI_TEAM_WORKFLOW.md'), 'utf8'),
    );
    const agentsPath = path.join(target, 'AGENTS.md');
    const agents = await readFile(agentsPath, 'utf8');
    expect(agents).toContain('](docs/HUMAN_AI_TEAM_WORKFLOW.md)');
    expect(agents).toContain('One writer per file set; separate checkout and branch');
    expect(agents).toContain(
      'No deployment, sends or paid tests without application/operator intent',
    );
    expect(await readFile(path.join(target, 'docs/QUICKSTART.md'), 'utf8')).toContain(
      '](HUMAN_AI_TEAM_WORKFLOW.md)',
    );
    expect((await checkDocumentation(target)).failures).toEqual([]);

    const pkg = JSON.parse(await readFile(path.join(target, 'package.json'), 'utf8'));
    expect(Object.keys(pkg.dependencies).sort()).toEqual(['next', 'react', 'react-dom', 'zod']);
    expect(pkg.scripts.agents).toBeUndefined();
    expect(plan.record.closure).toEqual([]);
    await expect(readFile(path.join(target, 'tools/agents/cli.ts'))).rejects.toThrow();
    await expect(readFile(path.join(target, '.codex/agents/orchestrator.toml'))).rejects.toThrow();

    const customized = '# Team-owned workflow\nOur recorded roles and approval owners.\n';
    await writeFile(workflowPath, customized);
    await writeFile(agentsPath, agents + '\nTeam-owned instructions.\n');
    const adoption = await planProject({
      target,
      ids: ['recommendations'],
      operation: 'add',
      catalog,
    });
    expect(adoption.conflicts).toEqual([]);
    await applyPlan(adoption);
    expect(await readFile(workflowPath, 'utf8')).toBe(customized);
    expect(await readFile(agentsPath, 'utf8')).toBe(agents + '\nTeam-owned instructions.\n');
  } finally {
    await rm(target, { recursive: true, force: true });
  }
});
