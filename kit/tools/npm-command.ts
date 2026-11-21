import { existsSync } from 'node:fs';
import path from 'node:path';

/** npm.cmd cannot be execFile'd on Windows; execute npm's JS entrypoint without a shell. */
export function npmCommand(args: string[]) {
  if (process.platform !== 'win32') return { file: 'npm', args };
  const dirs = [
    path.dirname(process.execPath),
    ...(process.env.PATH ?? process.env.Path ?? '').split(path.delimiter),
  ];
  const candidates = [
    process.env.npm_execpath,
    ...dirs.map((directory) => path.join(directory, 'node_modules/npm/bin/npm-cli.js')),
  ];
  const cli = candidates.find(
    (file): file is string => !!file && path.basename(file) === 'npm-cli.js' && existsSync(file),
  );
  if (!cli)
    throw new Error('Cannot locate npm-cli.js; start from npm run or install Node/npm on PATH');
  return { file: process.execPath, args: [cli, ...args] };
}
