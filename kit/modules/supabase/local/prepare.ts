import { createHash } from 'node:crypto';
import { lstat, mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { z } from 'zod';

export const LOCAL_PROJECT_ID = 'hackathon-kit-supabase-demo';
export const LOCAL_API_URL = 'http://127.0.0.1:56321';
const here = dirname(fileURLToPath(import.meta.url));
const markerName = '.kit-supabase-demo.json';
const migrationName = '20261009000000_notes.sql';
const MarkerSchema = z.object({
  projectId: z.literal(LOCAL_PROJECT_ID),
  apiUrl: z.literal(LOCAL_API_URL),
  configSha256: z.string().regex(/^[a-f0-9]{64}$/),
  migrationSha256: z.string().regex(/^[a-f0-9]{64}$/),
});
const sha = (text: string) => createHash('sha256').update(text).digest('hex');

async function rejectSymlinkPath(path: string): Promise<void> {
  const parent = dirname(path);
  if (parent !== path) await rejectSymlinkPath(parent);
  try {
    if ((await lstat(path)).isSymbolicLink())
      throw new Error('Local project paths must not contain symlinks');
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
  }
}
async function exactFile(path: string, content: string) {
  await rejectSymlinkPath(path);
  try {
    if ((await readFile(path, 'utf8')) !== content)
      throw new Error(`Refusing to overwrite changed local project file: ${path}`);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, content, { flag: 'wx' });
  }
}
export async function prepareLocalProject(target = '.kit/supabase-demo') {
  const directory = resolve(target);
  await rejectSymlinkPath(directory);
  const config = await readFile(join(here, 'supabase/config.toml'), 'utf8');
  const migration = await readFile(join(here, '../migrations/001_notes.sql'), 'utf8');
  const marker = MarkerSchema.parse({
    projectId: LOCAL_PROJECT_ID,
    apiUrl: LOCAL_API_URL,
    configSha256: sha(config),
    migrationSha256: sha(migration),
  });
  try {
    const files = await readdir(directory);
    if (files.length && !files.includes(markerName))
      throw new Error('Refusing nonempty directory without the demo project marker');
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
  }
  // The marker is written first so a partially completed setup can be safely retried.
  await exactFile(join(directory, markerName), `${JSON.stringify(marker, null, 2)}\n`);
  await exactFile(join(directory, 'supabase/config.toml'), config);
  await exactFile(join(directory, `supabase/migrations/${migrationName}`), migration);
  return { directory, ...marker };
}
export async function verifyLocalProject(target: string) {
  const directory = resolve(target);
  await rejectSymlinkPath(directory);
  const paths = [
    join(directory, markerName),
    join(directory, 'supabase/config.toml'),
    join(directory, `supabase/migrations/${migrationName}`),
  ];
  for (const path of paths) await rejectSymlinkPath(path);
  const [markerText, config, migration] = await Promise.all(
    paths.map((path) => readFile(path, 'utf8')),
  );
  const marker = MarkerSchema.parse(JSON.parse(markerText));
  if (sha(config) !== marker.configSha256 || sha(migration) !== marker.migrationSha256)
    throw new Error('Local project config or migration changed; inspect before seeding');
  // Compare to this checkout, not merely to a caller-editable marker.
  if (config !== (await readFile(join(here, 'supabase/config.toml'), 'utf8')))
    throw new Error('Local project is not the isolated demo configuration');
  return marker;
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const args = process.argv.slice(2);
  if (args.length && (args.length !== 2 || args[0] !== '--target'))
    throw new Error('Usage: prepare.ts [--target .kit/supabase-demo]');
  const result = await prepareLocalProject(args[1]);
  console.log(
    `Prepared ${result.projectId} at ${result.directory}. No services started or databases changed.`,
  );
}
