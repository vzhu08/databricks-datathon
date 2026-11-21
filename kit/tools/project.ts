import {
  readFile,
  writeFile,
  mkdir,
  stat,
  readdir,
  lstat,
  rename,
  unlink,
  realpath,
} from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { npmCommand } from './npm-command';
import { dependencyClosure, kitRoot, noSymlinks, safePath, walk } from './catalog';
import type { ModuleManifest } from '../catalog/manifest.schema';

export const recipes: Record<string, string[]> = {
  web: [],
  document: ['documents', 'retrieval', 'extraction', 'exports'],
  'document-python': ['documents', 'retrieval', 'extraction', 'exports'],
  group: ['recommendations', 'realtime'],
  media: ['media', 'voice', 'jobs'],
  full: [
    'documents',
    'retrieval',
    'extraction',
    'exports',
    'recommendations',
    'realtime',
    'media',
    'voice',
    'jobs',
    'maps',
    'analytics',
    'ai',
    'research',
    'supabase',
    'integrations',
  ],
};
type Package = {
  name?: string;
  dependencies?: Record<string, string>;
  devDependencies?: Record<string, string>;
  scripts?: Record<string, string>;
  [key: string]: unknown;
};
export type ProjectRecord = {
  schemaVersion: 1;
  starter: string;
  selected: string[];
  closure: string[];
  kitRevision: string;
  hashes: Record<string, string>;
};
export type Plan = {
  target: string;
  operation: 'create' | 'add';
  modules: string[];
  changes: { path: string; action: 'create' | 'update' | 'unchanged' }[];
  conflicts: string[];
  instructions: string[];
  files: Map<string, Buffer>;
  record: ProjectRecord;
  observed: Map<string, Buffer | undefined>;
};
async function canonicalDestination(target: string): Promise<string> {
  try {
    const info = await lstat(target);
    if (info.isSymbolicLink()) throw new Error(`Target itself cannot be a symlink: ${target}`);
    return await realpath(target);
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code !== 'ENOENT') throw e;
  }
  return path.join(await canonicalAncestor(path.dirname(target)), path.basename(target));
}
async function canonicalAncestor(target: string): Promise<string> {
  try {
    return await realpath(target);
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code !== 'ENOENT') throw e;
    return path.join(await canonicalAncestor(path.dirname(target)), path.basename(target));
  }
}
async function assertDestination(target: string) {
  if ((await canonicalDestination(target)) !== target)
    throw new Error('Target root/ancestor changed since planning; create a fresh plan');
}
const hash = (b: Buffer) => createHash('sha256').update(b).digest('hex');
const json = (v: unknown) => Buffer.from(JSON.stringify(v, null, 2) + '\n');
const exists = async (p: string) => !!(await stat(p).catch(() => null));
const pick = (obj: Record<string, string>, keys: string[]) =>
  Object.fromEntries(
    keys.map((k) => {
      if (!obj[k]) throw new Error(`Missing toolchain package ${k}`);
      return [k, obj[k]];
    }),
  );
export async function planProject({
  target,
  ids,
  starter = 'web',
  operation,
  catalog,
}: {
  target: string;
  ids: string[];
  starter?: string;
  operation: 'create' | 'add';
  catalog: ModuleManifest[];
}): Promise<Plan> {
  const destination = await canonicalDestination(path.resolve(target));
  if (destination === kitRoot || kitRoot.startsWith(destination + path.sep))
    throw new Error('Target must not be the kit or its ancestor');
  if (!Object.hasOwn(recipes, starter))
    throw new Error(`Unknown starter ${starter}. Use ${Object.keys(recipes).join(', ')}`);
  const files = new Map<string, Buffer>(),
    conflicts: string[] = [],
    instructions: string[] = [];
  let old: ProjectRecord | undefined;
  if (await exists(path.join(destination, 'kit.project.json')))
    old = JSON.parse(await readFile(path.join(destination, 'kit.project.json'), 'utf8'));
  const selected = [...new Set([...(old?.selected ?? []), ...recipes[starter], ...ids])];
  const modules = dependencyClosure(selected, catalog);
  const rootPkg: Package = JSON.parse(await readFile(path.join(kitRoot, 'package.json'), 'utf8'));
  const rootDeps = rootPkg.dependencies!,
    rootDev = rootPkg.devDependencies!;
  let pkg: Package;
  if (operation === 'create') {
    if ((await exists(destination)) && (await readdir(destination)).length)
      conflicts.push('Create target must be empty. Use add for an existing Next.js app.');
    pkg = {
      name:
        path
          .basename(destination)
          .toLowerCase()
          .replace(/[^a-z0-9-]/g, '-') || 'hackathon-project',
      version: '0.1.0',
      private: true,
      type: 'module',
      license: 'MIT',
      engines: { node: '>=22.23.0' },
      scripts: {
        dev: 'next dev --hostname 127.0.0.1',
        build: 'next build --webpack',
        start: 'next start --hostname 127.0.0.1',
        typecheck: 'tsc --noEmit',
        test: 'vitest run --passWithNoTests',
        check: 'npm run typecheck && npm test && npm run build',
      },
      dependencies: pick(rootDeps, ['next', 'react', 'react-dom', 'zod']),
      devDependencies: pick(rootDev, [
        'typescript',
        'tsx',
        'vitest',
        '@types/node',
        '@types/react',
        '@types/react-dom',
      ]),
    };
    for (const p of await walk(kitRoot, 'starters/web')) {
      const rel = p.slice('starters/web/'.length);
      if (['package.json', 'tsconfig.json', 'next-env.d.ts', 'README.md'].includes(rel)) continue;
      files.set(rel, await readFile(path.join(kitRoot, p)));
    }
    files.set(
      'tsconfig.json',
      json({
        compilerOptions: {
          target: 'ES2022',
          lib: ['dom', 'dom.iterable', 'es2022'],
          allowJs: true,
          skipLibCheck: true,
          strict: true,
          noEmit: true,
          esModuleInterop: true,
          module: 'esnext',
          moduleResolution: 'bundler',
          resolveJsonModule: true,
          isolatedModules: true,
          jsx: 'react-jsx',
          incremental: true,
          plugins: [{ name: 'next' }],
          paths: {
            '@kit/runtime': ['./packages/runtime/src/index.ts'],
            '@kit/contracts': ['./packages/contracts/src/index.ts'],
            '@kit/body': ['./packages/runtime/src/body.ts'],
          },
        },
        include: ['next-env.d.ts', '**/*.ts', '**/*.tsx', '.next/types/**/*.ts'],
        exclude: ['node_modules'],
      }),
    );
    files.set(
      '.gitignore',
      Buffer.from(
        'node_modules/\n.next/\n.env*\n!.env.example\n!.env.kit.example\n*.tsbuildinfo\n.venv/\n__pycache__/\n.kit/\n',
      ),
    );
    files.set(
      'AGENTS.md',
      Buffer.from(
        `# Project instructions\n\nThis is a standalone snapshot of Hackathon Kit. Read [selected modules](docs/kit/SELECTED_MODULES.md), [quickstart](docs/QUICKSTART.md), [ownership](docs/OWNERSHIP.md) and your task card before editing. Inspect scoped instructions explicitly.\n\nRead the [human–AI team workflow](docs/HUMAN_AI_TEAM_WORKFLOW.md) as human coordination context. Ask for actual human role and approval owners independently of worker accounts; existing technical controls remain authoritative and orchestration is optional.\n\n- Selected modules: ${modules.map((m) => m.id).join(', ') || 'none; base web only'}.\n- App routes: app/. Canonical capability code: modules/. Shared validation/runtime: packages/.\n- Run npm ci, npm run check, npm run dev. For an imported module use its README check command.\n- One writer per file set; separate checkout and branch per concurrent writer. Assign a human and steward for app/layout.tsx, global styles, package manifests/lockfile, contracts and migrations.\n- Validate boundary data; preserve fixture/live labels. No external API calls in ordinary tests.\n- Keep credentials server-side. No deployment, sends or paid tests without application/operator intent.\n- Preserve local modifications when upgrading this snapshot. Source revision and hashes: kit.project.json.\n- Return real checks, skipped prerequisites and handoff; do not claim deployment success from a local build.\n`,
      ),
    );
    files.set('CLAUDE.md', Buffer.from('@AGENTS.md\n'));
    files.set(
      'README.md',
      Buffer.from(
        `# ${pkg.name}\n\nGenerated local snapshot of Hackathon Kit.\n\n1. \`npm ci\` to install from the generated dependency lock. Commit package-lock.json with your project.\n2. \`npm run dev\` → http://localhost:3000\n3. \`npm run check\` verifies types, local tests and production build.\n\nSee [quickstart](docs/QUICKSTART.md), [selected capabilities](docs/kit/SELECTED_MODULES.md), [project brief](docs/PROJECT_BRIEF.md), [demo runbook](docs/DEMO_RUNBOOK.md) and [license](LICENSE). No provider credentials are required for local mode.\n`,
      ),
    );
    if (await exists(path.join(kitRoot, 'docs/templates')))
      for (const p of await walk(kitRoot, 'docs/templates'))
        files.set(
          'docs/' + p.slice('docs/templates/'.length),
          await readFile(path.join(kitRoot, p)),
        );
    files.set(
      'docs/QUICKSTART.md',
      Buffer.from(
        `# Quickstart\n\nNode >=22.23.0, npm. Run \`npm ci\` from the generated lockfile and commit it with the project. Run \`npm run dev\`, open http://localhost:3000 and normalize sample text. \`npm run check\` runs types, fixture tests and build. Chosen modules: ${modules.map((m) => m.id).join(', ') || 'none'}.\n\nRead the [human–AI team workflow](HUMAN_AI_TEAM_WORKFLOW.md) and record actual human role and approval owners. It is coordination context for manual teamwork or optional orchestration; existing technical controls govern implementation and release.\n\nOptional configuration names are in .env.kit.example and each module README. Copy only chosen live settings into an ignored .env.local. Never put private keys in NEXT_PUBLIC variables. See [selected modules](kit/SELECTED_MODULES.md).\n`,
      ),
    );
    files.set('LICENSE', await readFile(path.join(kitRoot, 'LICENSE')));
    if (starter !== 'web') {
      const kinds =
        starter === 'full'
          ? ['document', 'group', 'media']
          : [starter === 'document-python' ? 'document' : starter];
      const directories: Record<string, string> = {
        document: 'document-workbench',
        group: 'group-decision',
        media: 'media-assistant',
      };
      for (const kind of kinds) {
        const folder = 'examples/' + directories[kind];
        for (const p of await walk(kitRoot, folder))
          files.set(p, await readFile(path.join(kitRoot, p)));
        files.set(
          folder + '/README.md',
          Buffer.from(
            `# ${directories[kind]}\n\nRun npm ci, npm run dev, then open http://localhost:3000/${starter === 'full' ? 'kit/' + kind : 'kit'}. Run npm run check. This is a local composition using the modules recorded in kit.project.json. Read their guides under modules/. For the separate room server run npm run realtime when selected. Live adapters require explicit configuration; no credentials are needed for the sample.\n`,
          ),
        );
        const route = starter === 'full' ? `app/kit/${kind}/page.tsx` : 'app/kit/page.tsx';
        files.set(
          route,
          Buffer.from(
            `export {default} from '${starter === 'full' ? '../../../' : '../../'}${folder}/page';\n`,
          ),
        );
        if (kind === 'document')
          for (const [routeName, sourceName] of [
            ['documents', 'ingest'],
            ['report', 'report'],
          ])
            files.set(
              `app/api/kit/${routeName}/route.ts`,
              Buffer.from(
                `export {POST} from '../../../../examples/document-workbench/routes/${sourceName}';\nexport const runtime='nodejs';\n`,
              ),
            );
        if (kind === 'document')
          files.set(
            'app/api/kit/share/route.ts',
            Buffer.from(
              "export {GET,POST,DELETE} from '../../../../examples/document-workbench/routes/share';\nexport const runtime='nodejs';\n",
            ),
          );
        if (kind === 'media')
          files.set(
            'app/api/kit/jobs/route.ts',
            Buffer.from(
              "export {GET,POST,DELETE} from '../../../../examples/media-assistant/routes/jobs';\nexport const runtime='nodejs';\n",
            ),
          );
      }
      const resets = kinds.filter((k) => k === 'document' || k === 'media');
      if (resets.length)
        files.set(
          'app/api/kit/reset/route.ts',
          Buffer.from(
            resets
              .map((k) =>
                k === 'document'
                  ? "import {resetDemoShares} from '../../../../examples/document-workbench/routes/share';"
                  : "import {resetDemoJobs} from '../../../../examples/media-assistant/routes/jobs';",
              )
              .join('\n') +
              "\nimport {authorizeDemoReset} from '../../../../packages/runtime/src/demo-reset';\nimport {errorResponse} from '../../../../packages/runtime/src/index';\nexport const runtime='nodejs';\nexport async function POST(request:Request){try{authorizeDemoReset(request);" +
              resets
                .map((k) => (k === 'document' ? 'resetDemoShares();' : 'resetDemoJobs();'))
                .join('') +
              "return Response.json({reset:['local memory state'],next:'Reload browser pages; restart realtime server separately if running.'});}catch(e){return errorResponse(e);}}\n",
          ),
        );
      if (starter === 'full')
        files.set(
          'app/kit/page.tsx',
          Buffer.from(
            `export default function Kit(){return <section className="hero"><h1>Capability studio</h1><p><a href="/kit/document">Documents</a> · <a href="/kit/group">Decisions</a> · <a href="/kit/media">Media</a></p></section>;}\n`,
          ),
        );
      for (const p of await walk(kitRoot, 'packages/ui'))
        if (!p.endsWith('/package.json')) files.set(p, await readFile(path.join(kitRoot, p)));
      files.set(
        'examples/showcase-theme.css',
        await readFile(path.join(kitRoot, 'examples/showcase/app/showcase.css')),
      );
      const layout = files.get('app/layout.tsx')!.toString();
      files.set(
        'app/layout.tsx',
        Buffer.from(
          "import '../packages/ui/src/theme.css';\nimport '../examples/showcase-theme.css';\n" +
            layout,
        ),
      );
      files.set(
        'next.config.mjs',
        Buffer.from(
          "export default {agentRules:false,poweredByHeader:false,serverExternalPackages:['pdfjs-dist','mammoth','@napi-rs/canvas','ws'],webpack(config){config.resolve.extensionAlias={...config.resolve.extensionAlias,'.js':['.ts','.tsx','.js']};return config;}};\n",
        ),
      );
      files.set(
        'README.md',
        Buffer.from(
          files.get('README.md')!.toString() +
            `\nOpen http://localhost:3000/kit for the ${starter} composition.\n`,
        ),
      );
      if (kinds.includes('group'))
        pkg.scripts!['realtime'] = 'node --import tsx modules/realtime/examples/server.ts';
    }
    if (starter === 'document-python')
      for (const p of await walk(kitRoot, 'starters/python'))
        files.set(p, await readFile(path.join(kitRoot, p)));
    if (starter === 'document-python') {
      files.set(
        'app/kit/page.tsx',
        Buffer.from(
          "import Workbench from '../../examples/document-workbench/page';\nimport PythonPanel from '../../starters/python/component-example';\nexport default function Page(){return <><Workbench/><PythonPanel/></>;}\n",
        ),
      );
      files.set(
        'app/api/kit/python/route.ts',
        Buffer.from(
          "export {POST} from '../../../../starters/python/route-example';\nexport const runtime='nodejs';\n",
        ),
      );
    }
  } else {
    if (!(await exists(path.join(destination, 'package.json'))))
      throw new Error(
        'Automatic adoption supports npm + Next App Router projects. No package.json found. Copy portable module source manually after reading its README.',
      );
    pkg = JSON.parse(await readFile(path.join(destination, 'package.json'), 'utf8'));
    if (
      !pkg.dependencies?.next ||
      (!(await exists(path.join(destination, 'app'))) &&
        !(await exists(path.join(destination, 'src/app'))))
    )
      conflicts.push(
        'Unsupported target: automatic adoption requires Next App Router. Follow the module README for portable/manual integration.',
      );
    if (
      (await exists(path.join(destination, 'pnpm-lock.yaml'))) ||
      (await exists(path.join(destination, 'yarn.lock')))
    )
      conflicts.push(
        'Automatic dependency updates support npm only. Add source manually or use npm in a reviewed conversion.',
      );
    instructions.push(
      'Existing app routes, aliases, AGENTS.md and CLAUDE.md are preserved. Link docs/kit/SELECTED_MODULES.md from your instructions after review.',
    );
    if (!pkg.dependencies) pkg.dependencies = {};
    if (!pkg.devDependencies) pkg.devDependencies = {};
  }
  if (operation === 'create' && modules.some((m) => m.id === 'ai')) {
    files.set(
      'app/ai/page.tsx',
      Buffer.from(
        "import {AIProcessingWidget} from '../../modules/ai/examples/widget';\nexport default function Page(){return <AIProcessingWidget/>;}\n",
      ),
    );
    files.set(
      'app/api/kit/ai/route.ts',
      Buffer.from(
        "export {POST} from '../../../../modules/ai/examples/route';\nexport const runtime='nodejs';\n",
      ),
    );
    files.set(
      'README.md',
      Buffer.from(
        files.get('README.md')!.toString() +
          '\nOptional AI processing is mounted at /ai with labeled fixture mode by default. See modules/ai/examples/README.example.md before an authorized live test.\n',
      ),
    );
  }
  pkg.dependencies ??= {};
  pkg.devDependencies ??= {};
  // Optional Supabase's shipped browser smoke is a developer-only dependency.
  if (modules.some((m) => m.id === 'supabase')) {
    const version = rootDev['@playwright/test'];
    const existing =
      pkg.devDependencies['@playwright/test'] ?? pkg.dependencies['@playwright/test'];
    if (existing && existing !== version)
      conflicts.push(`Dev package @playwright/test: ${existing} conflicts with ${version}`);
    else if (!existing) pkg.devDependencies['@playwright/test'] = version;
  }
  const dependencyEntries: [string, string][] = [
    ['zod', rootDeps.zod],
    ...modules.flatMap((m) => Object.entries(m.packages)),
  ];
  for (const [name, version] of dependencyEntries) {
    const current = pkg.dependencies[name] ?? pkg.devDependencies[name];
    if (current && current !== version)
      conflicts.push(
        `Package ${name}: target has ${current}; module tested with ${version}. Resolve and re-run, or integrate manually.`,
      );
    else if (!current) pkg.dependencies[name] = version;
  }
  if (modules.length) {
    for (const [name, version] of Object.entries(pick(rootDev, ['tsx', 'vitest']))) {
      const existing = pkg.devDependencies[name] ?? pkg.dependencies[name];
      if (existing && existing !== version)
        conflicts.push(`Dev package ${name}: ${existing} conflicts with ${version}`);
      else if (!existing) pkg.devDependencies[name] = version;
    }
    const typeDeps: Record<string, string> = {
      papaparse: '@types/papaparse',
      qrcode: '@types/qrcode',
      ws: '@types/ws',
    };
    for (const [dep, type] of Object.entries(typeDeps))
      if (pkg.dependencies[dep] && !pkg.devDependencies[type])
        pkg.devDependencies[type] = rootDev[type];
  }
  for (const rel of [
    'packages/contracts',
    'packages/runtime',
    ...modules.flatMap((m) => m.exports),
  ])
    for (const p of await walk(kitRoot, rel)) {
      if (p.endsWith('/package.json') && p.startsWith('packages/')) continue;
      files.set(p, await readFile(path.join(kitRoot, p)));
    }
  files.set('package.json', json(pkg));
  const env = new Map(modules.flatMap((m) => m.env.map((e) => [e.name, e] as const)));
  if (starter === 'document-python' || old?.starter === 'document-python')
    env.set('PYTHON_API_URL', {
      name: 'PYTHON_API_URL',
      required: false,
      secret: false,
      when: 'optional',
      description: 'Server-reachable optional FastAPI base URL; defaults to http://127.0.0.1:8000.',
    });
  files.set(
    '.env.kit.example',
    Buffer.from(
      '# Only configure explicitly selected live adapters. No credentials needed for local mode.\n' +
        [...env.values()]
          .map(
            (e) =>
              `# ${e.when}; ${e.secret ? 'secret; server only' : 'non-secret'}; ${e.description}\n${e.name}=`,
          )
          .join('\n') +
        '\n',
    ),
  );
  files.set(
    'docs/kit/SELECTED_MODULES.md',
    Buffer.from(
      `# Selected capabilities\n\nSnapshot starter: ${old?.starter ?? starter}. Source revision is in kit.project.json. Module-guide creation/adoption CLI commands run from the source toolkit checkout; source examples and test commands run here. Imports keep the original modules/ and packages/ layout; no connection to the source checkout is required.\n\n${modules.map((m) => `## ${m.title}\n\n[Module guide](../../modules/${m.id}/README.md) · entry: \`${Object.values(m.entrypoints)[0]}\`\n\n${m.description}\n\nIntegration: ${m.integration.steps.join(' ')}\n\nChecks: ${m.checks.map((c) => '`' + c + '`').join('; ')}. Live status: ${m.verification.live}.\n`).join('\n') || 'Base web only; no optional modules selected.\n'}\n## Updating\n\nReview source revision and hashes in kit.project.json. Keep customizations in version control. Re-run the kit plan command from an updated toolkit and compare before applying; changed imported files cause conflicts. Never assume a fresh import safely merges your edits.\n`,
    ),
  );
  let revision = 'uncommitted';
  try {
    revision = execFileSync('git', ['rev-parse', 'HEAD'], {
      cwd: kitRoot,
      encoding: 'utf8',
    }).trim();
    if (execFileSync('git', ['status', '--porcelain'], { cwd: kitRoot, encoding: 'utf8' }).trim())
      revision += '-dirty';
  } catch {}
  const record: ProjectRecord = {
    schemaVersion: 1,
    starter: old?.starter ?? starter,
    selected,
    closure: modules.map((m) => m.id),
    kitRevision: revision,
    hashes: { ...old?.hashes },
  };
  const changes: Plan['changes'] = [];
  const observed = new Map<string, Buffer | undefined>();
  for (const [p, content] of files) {
    safePath(destination, p);
    await noSymlinks(destination, p);
    const targetPath = path.join(destination, p);
    const previous = await readFile(targetPath).catch((e) => {
      if (e.code === 'ENOENT') return undefined;
      throw e;
    });
    observed.set(p, previous);
    const digest = hash(content);
    record.hashes[p] = digest;
    const action: 'create' | 'update' | 'unchanged' = previous
      ? hash(previous) === digest
        ? 'unchanged'
        : 'update'
      : 'create';
    if (
      action === 'update' &&
      operation === 'add' &&
      p !== 'package.json' &&
      (!old?.hashes[p] || hash(previous!) !== old.hashes[p])
    )
      conflicts.push(
        `File ${p} exists and differs. Preserve it; compare manually or relocate before adopting.`,
      );
    if (
      action === 'update' &&
      p === 'package.json' &&
      old?.hashes[p] &&
      hash(previous!) !== old.hashes[p]
    )
      instructions.push(
        'package.json has local changes; only missing dependencies are merged; existing scripts and metadata preserved.',
      );
    changes.push({ path: p, action });
  }
  files.set('kit.project.json', json(record));
  const oldRecord = await readFile(path.join(destination, 'kit.project.json')).catch(
    () => undefined,
  );
  observed.set('kit.project.json', oldRecord);
  changes.push({
    path: 'kit.project.json',
    action: oldRecord ? (oldRecord.equals(json(record)) ? 'unchanged' : 'update') : 'create',
  });
  for (const m of modules) {
    instructions.push(...m.integration.steps.map((s) => `${m.id}: ${s}`));
    if (m.integration.routes.length)
      instructions.push(
        `${m.id}: route registration is manual and reviewable: ${m.integration.routes.join(', ')}; no existing routes are rewritten.`,
      );
    if (m.integration.migrations.length)
      instructions.push(
        `${m.id}: migrations must be reviewed for table/policy names against the target database; they are copied but never applied automatically.`,
      );
  }
  if (changes.some((c) => c.path === 'package.json' && c.action !== 'unchanged'))
    instructions.push(
      'Run npm install to resolve/update package-lock.json, review the diff, then npm run check (or your existing app checks) and selected module tests.',
    );
  return {
    target: destination,
    operation,
    modules: modules.map((m) => m.id),
    changes,
    conflicts: [...new Set(conflicts)],
    instructions: [...new Set(instructions)],
    files,
    record,
    observed,
  };
}
export async function applyPlan(plan: Plan) {
  if (plan.conflicts.length) throw new Error(`Refusing writes:\n${plan.conflicts.join('\n')}`);
  await assertDestination(plan.target);
  for (const [p, expected] of plan.observed) {
    await noSymlinks(plan.target, p);
    const current = await readFile(path.join(plan.target, p)).catch((e) => {
      if (e.code === 'ENOENT') return undefined;
      throw e;
    });
    if (
      current === undefined
        ? expected !== undefined
        : expected === undefined || !current.equals(expected)
    )
      throw new Error(
        `Target changed after planning: ${p}. Create a fresh plan; no files written.`,
      );
  }
  const written: string[] = [];
  try {
    for (const change of plan.changes.filter((c) => c.action !== 'unchanged')) {
      const p = change.path;
      await assertDestination(plan.target);
      await noSymlinks(plan.target, p);
      const target = safePath(plan.target, p);
      await mkdir(path.dirname(target), { recursive: true });
      const temp = target + `.kit-${crypto.randomUUID()}.tmp`;
      try {
        await writeFile(temp, plan.files.get(p)!, { flag: 'wx' });
        await rename(temp, target);
        written.push(p);
      } finally {
        await unlink(temp).catch(() => {});
      }
    }
  } catch (error) {
    await assertDestination(plan.target);
    for (const p of written.reverse()) {
      await noSymlinks(plan.target, p);
      const previous = plan.observed.get(p);
      const target = safePath(plan.target, p);
      if (previous) await writeFile(target, previous);
      else await unlink(target).catch(() => {});
    }
    throw error;
  }
}
export function printablePlan(plan: Plan) {
  return {
    target: plan.target,
    operation: plan.operation,
    modules: plan.modules,
    changes: plan.changes,
    conflicts: plan.conflicts,
    instructions: plan.instructions,
  };
}

/** Prune the tested toolkit lock to the selected closure without network or install scripts. */
export async function materializeLock(plan: Plan) {
  if (plan.operation !== 'create') return;
  await assertDestination(plan.target);
  const pkg = JSON.parse(plan.files.get('package.json')!.toString());
  const lock = JSON.parse(await readFile(path.join(kitRoot, 'package-lock.json'), 'utf8'));
  lock.name = pkg.name;
  lock.version = pkg.version;
  lock.packages = Object.fromEntries(
    Object.entries(lock.packages).filter(
      ([p, v]) => p.startsWith('node_modules/') && !(v as { link?: boolean }).link,
    ),
  );
  lock.packages[''] = {
    name: pkg.name,
    version: pkg.version,
    license: pkg.license,
    dependencies: pkg.dependencies,
    devDependencies: pkg.devDependencies,
    engines: pkg.engines,
  };
  const lockPath = path.join(plan.target, 'package-lock.json');
  await noSymlinks(plan.target, 'package-lock.json');
  await writeFile(lockPath, json(lock), { flag: 'wx' });
  try {
    const npm = npmCommand([
      'install',
      '--package-lock-only',
      '--ignore-scripts',
      '--offline',
      '--no-audit',
      '--no-fund',
      '--cache',
      path.join(plan.target, '.kit/npm-cache'),
    ]);
    execFileSync(npm.file, npm.args, { cwd: plan.target, stdio: 'pipe', timeout: 120_000 });
  } catch {
    await unlink(lockPath);
    throw new Error(
      `Project source generated at ${plan.target}, but offline lock pruning failed. Run npm install there once, inspect and commit package-lock.json before using npm ci.`,
    );
  }
  plan.record.hashes['package-lock.json'] = hash(await readFile(lockPath));
  await writeFile(path.join(plan.target, 'kit.project.json'), json(plan.record));
}
