import { execFileSync } from 'node:child_process';
import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import net from 'node:net';
import { type ModuleManifest } from '../catalog/manifest.schema';
export async function doctor(target: string, modules: ModuleManifest[], port?: number) {
  const results: { check: string; status: 'pass' | 'warning' | 'fail'; detail: string }[] = [];
  results.push({
    check: 'Node.js',
    status:
      Number(process.versions.node.split('.')[0]) > 22 ||
      (Number(process.versions.node.split('.')[0]) === 22 &&
        Number(process.versions.node.split('.')[1]) >= 23)
        ? 'pass'
        : 'fail',
    detail: `${process.version}; install Node >=22.23.0`,
  });
  try {
    results.push({
      check: 'npm',
      status: 'pass',
      detail: execFileSync('npm', ['--version'], { encoding: 'utf8' }).trim(),
    });
  } catch {
    results.push({ check: 'npm', status: 'fail', detail: 'Install npm with Node.js' });
  }
  const pkg = JSON.parse(
    await readFile(path.join(target, 'package.json'), 'utf8').catch(() => '{}'),
  );
  results.push({
    check: 'project',
    status: pkg.name ? 'pass' : 'warning',
    detail: pkg.name
      ? `Project ${pkg.name}`
      : 'No package.json in target; pass --target to a project',
  });
  results.push({
    check: 'lockfile',
    status: (await stat(path.join(target, 'package-lock.json')).catch(() => null))
      ? 'pass'
      : 'warning',
    detail:
      'Run npm install once to create/update package-lock.json, then commit it and use npm ci',
  });
  for (const m of modules) {
    for (const e of m.env)
      if (!process.env[e.name])
        results.push({
          check: `${m.id}/${e.name}`,
          status: e.required && e.when === 'local' ? 'fail' : 'warning',
          detail: `Not set in process; ${e.when} only. ${e.description}. Values are never printed. .env files are not read by doctor.`,
        });
    for (const requirement of m.systemRequirements)
      results.push({ check: `${m.id}/system`, status: 'warning', detail: requirement });
  }
  const pythonStarter = await stat(path.join(target, 'starters/python/pyproject.toml')).catch(
    () => null,
  );
  if (
    pythonStarter?.isFile() ||
    modules.some((m) => m.runtime === 'python' || m.exports.includes('starters/python'))
  ) {
    for (const bin of ['python3', 'uv']) {
      try {
        const projectPython = path.join(target, 'starters/python/.venv/bin/python');
        const command =
          bin === 'python3' && (await stat(projectPython).catch(() => null)) ? projectPython : bin;
        const version = execFileSync(command, ['--version'], { encoding: 'utf8' }).trim();
        const match = /Python (\d+)\.(\d+)/.exec(version);
        const supported =
          bin !== 'python3' ||
          (!!match && Number(match[1]) === 3 && Number(match[2]) >= 12 && Number(match[2]) < 14);
        results.push({
          check: bin,
          status: supported ? 'pass' : 'warning',
          detail: supported
            ? `${version}; ${command}`
            : `${version} is outside Python 3.12–3.13. Install with uv and run uv sync --frozen --python 3.12 in starters/python.`,
        });
      } catch {
        results.push({
          check: bin,
          status: 'warning',
          detail: `Install ${bin} only for the selected Python/OCR path; see starters/python/README.md`,
        });
      }
    }
  }
  if (port !== undefined) {
    if (!Number.isInteger(port) || port < 1 || port > 65535)
      throw new Error('Port must be 1–65535');
    const occupied = await new Promise<boolean>((resolve) => {
      const socket = net.connect({ host: '127.0.0.1', port });
      socket.setTimeout(600);
      socket.once('connect', () => {
        socket.destroy();
        resolve(true);
      });
      socket.once('error', () => resolve(false));
      socket.once('timeout', () => {
        socket.destroy();
        resolve(false);
      });
    });
    results.push({
      check: `localhost:${port}`,
      status: occupied ? 'warning' : 'pass',
      detail: occupied
        ? 'Port accepts TCP connections; use a distinct port or verify the expected local service'
        : 'Port is available; no service is listening',
    });
  }
  return {
    target,
    mode: 'local-read-only',
    results,
    healthy: results.every((r) => r.status !== 'fail'),
  };
}
