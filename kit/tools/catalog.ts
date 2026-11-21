import { readdir, readFile, stat, lstat, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { z } from 'zod';
import { ModuleManifestSchema, type ModuleManifest } from '../catalog/manifest.schema';
import {
  ApiErrorSchema,
  DocumentSchema,
  CitationSchema,
  JobSchema,
  TransformRequestSchema,
  TransformResultSchema,
} from '../packages/contracts/src/index';

export const kitRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export function safePath(root: string, relative: string): string {
  if (
    !relative ||
    relative.includes('\\') ||
    relative.includes('\0') ||
    path.isAbsolute(relative) ||
    /^[a-zA-Z]:/.test(relative) ||
    relative.split('/').some((p) => p === '..' || p === '' || p === '.')
  )
    throw new Error(`Unsafe manifest path: ${relative}`);
  const resolved = path.resolve(root, relative);
  if (!resolved.startsWith(path.resolve(root) + path.sep))
    throw new Error(`Path escapes target: ${relative}`);
  return resolved;
}
export async function noSymlinks(root: string, relative: string) {
  safePath(root, relative);
  let current = path.resolve(root);
  for (const part of relative.split('/')) {
    current = path.join(current, part);
    try {
      if ((await lstat(current)).isSymbolicLink())
        throw new Error(`Symlink is not an export destination/source: ${current}`);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') break;
      throw error;
    }
  }
}
export async function walk(root: string, relative: string): Promise<string[]> {
  await noSymlinks(root, relative);
  const target = safePath(root, relative),
    info = await stat(target);
  if (info.isFile()) return [relative];
  const result: string[] = [];
  for (const item of (await readdir(target)).sort()) {
    if (
      (item.startsWith('.env') &&
        item !== '.env.example' &&
        !/^\.env\.[a-zA-Z0-9_-]+\.example$/.test(item)) ||
      /\.(pem|key|p12|pfx|jks)$/.test(item)
    )
      continue;
    if (
      [
        'node_modules',
        '.next',
        '.venv',
        '__pycache__',
        '.pytest_cache',
        '.DS_Store',
        '.git',
        '.aws',
        '.ssh',
        '.npmrc',
        '.netrc',
        '.kit',
      ].includes(item) ||
      item.endsWith('.tsbuildinfo')
    )
      continue;
    result.push(...(await walk(root, `${relative}/${item}`)));
  }
  return result;
}
export async function readCatalog(root = kitRoot): Promise<ModuleManifest[]> {
  const folder = path.join(root, 'modules');
  let dirs: string[] = [];
  try {
    dirs = await readdir(folder);
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code !== 'ENOENT') throw e;
  }
  const modules: ModuleManifest[] = [];
  for (const id of dirs.sort()) {
    if (!(await stat(path.join(folder, id))).isDirectory()) continue;
    const manifest = ModuleManifestSchema.parse(
      JSON.parse(await readFile(path.join(folder, id, 'module.json'), 'utf8')),
    );
    if (id !== manifest.id) throw new Error(`Module ID/directory mismatch: ${id}`);
    modules.push(manifest);
  }
  dependencyClosure(
    modules.map((m) => m.id),
    modules,
  );
  for (const m of modules) {
    if (m.source !== `modules/${m.id}/src`)
      throw new Error(`Module ${m.id} source must be its own src directory`);
    for (const p of [
      m.source,
      ...Object.values(m.entrypoints),
      ...m.exports,
      ...m.minimalRead,
      ...m.contracts,
      ...m.examples,
      ...m.fixtures,
      ...m.integration.assets,
      ...m.integration.migrations,
      m.verification.record,
      ...m.docs.filter((p) => !/^https?:/.test(p)),
    ]) {
      await noSymlinks(root, p);
      await stat(safePath(root, p)).catch(() => {
        throw new Error(`${m.id}: missing path ${p}`);
      });
    }
    for (const p of m.exports)
      if (!p.startsWith(`modules/${m.id}/`) && p !== `modules/${m.id}` && p !== 'starters/python')
        throw new Error(`${m.id}: exports may only contain its module or optional Python starter`);
    for (const env of m.env)
      if (env.secret && env.name.startsWith('NEXT_PUBLIC_'))
        throw new Error(`${m.id}: secret cannot be NEXT_PUBLIC`);
    for (const [name, version] of Object.entries(m.packages))
      if (!/^[\w@][\w@/.-]*$/.test(name) || !/^\d+\.\d+\.\d+(?:-[\w.-]+)?$/.test(version))
        throw new Error(`${m.id}: packages must use exact versions: ${name}`);
  }
  return modules;
}
export function dependencyClosure(ids: string[], catalog: ModuleManifest[]): ModuleManifest[] {
  const byId = new Map(catalog.map((m) => [m.id, m]));
  if (byId.size !== catalog.length) throw new Error('Duplicate module ID');
  const done = new Set<string>(),
    visiting = new Set<string>(),
    sorted: ModuleManifest[] = [];
  function visit(id: string) {
    const m = byId.get(id);
    if (!m) throw new Error(`Unknown module: ${id}. Run kit list.`);
    if (visiting.has(id)) throw new Error(`Module dependency cycle involving ${id}`);
    if (done.has(id)) return;
    visiting.add(id);
    m.dependencies.forEach(visit);
    visiting.delete(id);
    done.add(id);
    sorted.push(m);
  }
  ids.forEach(visit);
  return sorted;
}
export function catalogMarkdown(modules: ModuleManifest[]) {
  return `# Capability catalog\n\nGenerated from module manifests. Run \`npm run kit -- inspect <id>\` for prerequisites, contracts, examples and verification status. Only selected capabilities and their dependency closure are copied to a project.\n\n| Capability | Purpose | Runtime | Dependencies |\n|---|---|---|---|\n${modules.map((m) => `| [${m.id}](modules/${m.id}/README.md) | ${m.description.replace(/\|/g, '\\|')} | ${m.runtime} | ${m.dependencies.join(', ') || 'none'} |`).join('\n')}\n\n## Task-to-module map\n\n${modules.map((m) => `- ${m.useCases.join('; ')} → [${m.id}](modules/${m.id}/README.md)`).join('\n')}\n`;
}
export async function generatedCatalogFiles(modules: ModuleManifest[]) {
  const json = (v: unknown) => JSON.stringify(v, null, 2) + '\n';
  return new Map([
    ['CATALOG.md', catalogMarkdown(modules)],
    ['catalog/modules.json', json({ schemaVersion: 1, modules })],
    ['catalog/module.schema.json', json(z.toJSONSchema(ModuleManifestSchema))],
    [
      'packages/contracts/schema.json',
      json({
        $schema: 'https://json-schema.org/draft/2020-12/schema',
        $defs: Object.fromEntries(
          Object.entries({
            ApiError: ApiErrorSchema,
            Document: DocumentSchema,
            Citation: CitationSchema,
            Job: JobSchema,
            TransformRequest: TransformRequestSchema,
            TransformResult: TransformResultSchema,
          }).map(([k, v]) => [
            k,
            z.toJSONSchema(v, {
              unrepresentable: 'any',
              ...(k === 'TransformRequest' ? { io: 'input' as const } : {}),
            }),
          ]),
        ),
      }),
    ],
  ]);
}
export async function buildCatalog(check = false, root = kitRoot) {
  const modules = await readCatalog(root);
  for (const [relative, text] of await generatedCatalogFiles(modules)) {
    if (check) {
      const actual = await readFile(path.join(root, relative), 'utf8').catch(() => '');
      if (actual.replace(/\r\n/g, '\n') !== text)
        throw new Error(`${relative} is stale. Run npm run kit -- catalog build.`);
    } else {
      await mkdir(path.dirname(path.join(root, relative)), { recursive: true });
      await writeFile(path.join(root, relative), text);
    }
  }
  return modules;
}
