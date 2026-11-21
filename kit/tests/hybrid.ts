import { spawn } from 'node:child_process';
import { once } from 'node:events';
import path from 'node:path';
import assert from 'node:assert/strict';
import { POST } from '../starters/python/route-example';
import { TransformResultSchema } from '../packages/contracts/src/index';
const executable =
  process.env.KIT_PYTHON_EXECUTABLE ?? path.resolve('starters/python/.venv/bin/python');
const python = spawn(
  executable,
  ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '3950'],
  { cwd: path.resolve('starters/python'), stdio: ['ignore', 'pipe', 'pipe'] },
);
let log = '';
python.stderr.on('data', (v) => {
  log += v;
});
try {
  let ready = false;
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch('http://127.0.0.1:3950/ready')).ok) {
        ready = true;
        break;
      }
    } catch {}
    await new Promise((r) => setTimeout(r, 50));
  }
  assert(ready, log);
  process.env.PYTHON_API_URL = 'http://127.0.0.1:3950';
  const response = await POST(
    new Request('http://localhost/api/kit/python', {
      method: 'POST',
      body: JSON.stringify({ text: '  Team   🌱\r\n  working  together  ' }),
    }),
  );
  assert.equal(response.status, 200);
  const result = TransformResultSchema.parse(await response.json());
  assert.equal(result.text, 'Team 🌱\nworking together');
  assert.equal(result.characters, result.text.length);
  const malformed = await POST(
    new Request('http://localhost/api/kit/python', { method: 'POST', body: '{' }),
  );
  assert.equal(malformed.status, 400);
  console.log(
    JSON.stringify({
      flow: 'TypeScript route → real loopback HTTP → FastAPI → shared validated response',
      status: 'passed',
      unicode: true,
      malformedInput: true,
    }),
  );
} finally {
  python.kill('SIGTERM');
  if (python.exitCode === null) await once(python, 'exit');
}
