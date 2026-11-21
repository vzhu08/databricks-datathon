'use client';
import { useState } from 'react';
import { TransformResultSchema } from '../../packages/contracts/src/index';
export default function PythonPanel() {
  const [text, setText] = useState('  Shared   contracts  across   runtimes.  '),
    [result, setResult] = useState(''),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  return (
    <section className="panel">
      <p className="eyebrow">OPTIONAL PYTHON COMPANION</p>
      <h2>Try the second runtime.</h2>
      <p>
        Start the separate FastAPI service, then send text through the web server. The response is
        checked against the same contract used by the local TypeScript transformation.
      </p>
      <label>
        Python input
        <textarea
          aria-label="Python input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={100000}
        />
      </label>
      <button
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError('');
          try {
            const response = await fetch('/api/kit/python', {
              method: 'POST',
              headers: { 'content-type': 'application/json' },
              body: JSON.stringify({ text }),
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error?.message ?? 'Python service unavailable');
            setResult(TransformResultSchema.parse(data).text);
          } catch (e) {
            setError(
              (e instanceof Error ? e.message : 'Service unavailable') +
                '. Check the separate Python server and PYTHON_API_URL.',
            );
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? 'Processing…' : 'Normalize with Python'}
      </button>
      {result && <output aria-label="Python result">{result}</output>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
