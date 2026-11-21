import { readdir, readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { kitRoot, readCatalog } from './catalog';

export async function checkDocumentation(root = kitRoot) {
  const failures: string[] = [];
  let files = 0,
    links = 0;
  async function visit(directory: string) {
    for (const item of await readdir(directory, { withFileTypes: true })) {
      if (
        [
          'node_modules',
          '.next',
          '.git',
          '.kit',
          '.venv',
          'test-results',
          'playwright-report',
          '__pycache__',
        ].includes(item.name)
      )
        continue;
      const filename = path.join(directory, item.name);
      if (item.isDirectory()) {
        await visit(filename);
        continue;
      }
      if (!item.isFile() || !item.name.endsWith('.md')) continue;
      files++;
      const source = (await readFile(filename, 'utf8')).replace(/```[\s\S]*?```/g, '');
      for (const match of source.matchAll(/\[[^\]\n]+\]\(([^)\n]+)\)/g)) {
        const href = match[1].replace(/^<|>$/g, '').split(/\s+"/)[0];
        if (/^(?:https?:|mailto:|#)/.test(href)) continue;
        const target = decodeURIComponent(href.split('#')[0]);
        if (!target) continue;
        links++;
        if (path.isAbsolute(target) || /^[a-z]+:/i.test(target)) {
          failures.push(`${path.relative(root, filename)}: nonportable local link ${href}`);
          continue;
        }
        if (!(await stat(path.resolve(path.dirname(filename), target)).catch(() => null)))
          failures.push(`${path.relative(root, filename)}: missing ${href}`);
      }
    }
  }
  await visit(root);
  if (root === kitRoot) {
    await readCatalog();
    if ((await readFile(path.join(root, 'AGENTS.md'), 'utf8')).split('\n').length > 150)
      failures.push('Root AGENTS.md exceeds the 150-line navigation budget');
  }
  return { files, links, failures };
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const report = await checkDocumentation();
  console.log(JSON.stringify(report, null, 2));
  if (report.failures.length) process.exitCode = 1;
}
