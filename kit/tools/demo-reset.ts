import { parseArgs } from 'node:util';

const defaultUrl = 'http://127.0.0.1:3001';
const timeoutMs = 10_000;

function resetTarget(input: string): URL {
  let url: URL;
  try {
    url = new URL(input);
  } catch {
    throw new Error('--url must be an absolute loopback HTTP origin, for example ' + defaultUrl);
  }
  if (
    url.protocol !== 'http:' ||
    !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) ||
    url.username ||
    url.password ||
    input.includes('@') ||
    url.pathname !== '/' ||
    input.includes('?') ||
    input.includes('#')
  ) {
    throw new Error(
      '--url must be an HTTP origin on localhost, 127.0.0.1, or [::1], without userinfo, a path, query, or fragment.',
    );
  }
  return new URL('/api/kit/reset', url.origin);
}

async function main() {
  const { values } = parseArgs({
    options: {
      url: { type: 'string', default: defaultUrl },
      apply: { type: 'boolean', default: false },
      help: { type: 'boolean', default: false },
    },
  });
  if (values.help) {
    console.log(
      'Usage: node --import tsx tools/demo-reset.ts [--url http://127.0.0.1:3001] [--apply]\n' +
        'Dry-run is the default. --apply clears the active local demo server’s in-memory jobs and shares.',
    );
    return;
  }
  const target = resetTarget(values.url);
  const headers = { Origin: target.origin, 'x-kit-demo-reset': 'confirm' };
  console.log(
    JSON.stringify(
      {
        target: target.href,
        method: 'POST',
        headers,
        mode: values.apply ? 'apply' : 'dry-run',
        status: values.apply ? 'requesting' : 'not sent; pass --apply to reset',
        timeoutMs,
        scope: 'Active local demo server in-memory jobs and shares',
        separateSteps: [
          'Restart the realtime room server to clear its in-memory rooms.',
          'Reload browser tabs to reset their local component state.',
        ],
      },
      null,
      2,
    ),
  );
  if (!values.apply) return;

  const response = await fetch(target, {
    method: 'POST',
    headers,
    redirect: 'manual',
    signal: AbortSignal.timeout(timeoutMs),
  });
  console.log(
    JSON.stringify({
      target: target.href,
      status: response.status,
      statusText: response.statusText,
    }),
  );
  if (!response.ok) {
    await response.body?.cancel();
    throw new Error(`Reset failed: HTTP ${response.status} from ${target.href}`);
  }
  await response.body?.cancel();
  console.log(
    'Reset complete. Restart the realtime room server and reload browser tabs for a fresh demo.',
  );
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
