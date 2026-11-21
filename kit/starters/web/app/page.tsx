'use client';
import { useRef, useState } from 'react';
import { TransformResultSchema, type TransformResult } from '@kit/contracts';
export default function Home() {
  const [text, setText] = useState(
      '  A great idea   starts here.\n\n Give it a little structure.  ',
    ),
    [result, setResult] = useState<TransformResult | null>(null),
    [error, setError] = useState(''),
    [loading, setLoading] = useState(false);
  const controller = useRef<AbortController | null>(null);
  async function run() {
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/transform', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text, operation: 'normalize' }),
        signal: request.signal,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error?.message ?? 'Transformation failed');
      setResult(TransformResultSchema.parse(data));
    } catch (e) {
      if (!request.signal.aborted)
        setError(e instanceof Error ? e.message : 'Something went wrong');
    } finally {
      if (controller.current === request) setLoading(false);
    }
  }
  return (
    <>
      <section className="hero">
        <p className="eyebrow">YOUR NEXT BUILD STARTS HERE</p>
        <h1>
          Less setup.
          <br />
          <span>More possibility.</span>
        </h1>
        <p className="lede">
          A small foundation for an ambitious idea. Transform your first input, then add only the
          capabilities your project needs.
        </p>
        <div className="meta">
          <span>TypeScript + Next.js</span>
          <span>Credential-free by default</span>
          <span>Yours to make</span>
        </div>
      </section>
      <section className="workbench" aria-labelledby="demo-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">01 / THE FIRST WORKING SLICE</p>
            <h2 id="demo-title">A little clarity, instantly.</h2>
          </div>
          <span className="badge">Real local transformation</span>
        </div>
        <div className="editor-grid">
          <div>
            <label htmlFor="text">Your input</label>
            <textarea
              id="text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              maxLength={100000}
              rows={7}
            />
            <div className="editor-bottom">
              <span>{text.length.toLocaleString()} characters</span>
              <button onClick={run} disabled={loading}>
                {loading ? 'Working…' : 'Normalize text'} <span aria-hidden>↗</span>
              </button>
              {loading && (
                <button
                  className="secondary"
                  onClick={() => {
                    controller.current?.abort();
                    setLoading(false);
                  }}
                >
                  Cancel
                </button>
              )}
            </div>
          </div>
          <div className="result" aria-live="polite">
            <p className="eyebrow">THE RESULT</p>
            {result ? (
              <>
                <p className="output-text">
                  {result.text || 'The input is empty. Add some text to begin.'}
                </p>
                <div className="result-stats">
                  <span>
                    <strong>{result.words}</strong> words
                  </span>
                  <span>
                    <strong>{result.characters}</strong> characters
                  </span>
                </div>
              </>
            ) : (
              <div className="empty">
                <span aria-hidden>✳</span>
                <p>A clearer version is one click away.</p>
                <small>Whitespace normalized. Line breaks preserved.</small>
              </div>
            )}
          </div>
        </div>
        {error && (
          <div role="alert" className="error">
            {error} <button onClick={run}>Try again</button>
          </div>
        )}
      </section>
      <section className="next-steps">
        <p className="eyebrow">MAKE IT YOURS</p>
        <h2>One foundation. Any direction.</h2>
        <div className="cards">
          <article>
            <span>01</span>
            <h3>Define the moment</h3>
            <p>
              Open docs/PROJECT_BRIEF.md. Name your user, their problem, and the workflow you’ll
              show the judges.
            </p>
          </article>
          <article>
            <span>02</span>
            <h3>Add a capability</h3>
            <p>
              Explore the module catalog. Bring in documents, recommendations, media, or a service
              when your idea calls for it.
            </p>
          </article>
          <article>
            <span>03</span>
            <h3>Build together</h3>
            <p>
              Agree on contracts, assign clear file ownership, and keep integrating small, working
              improvements.
            </p>
          </article>
        </div>
      </section>
    </>
  );
}
