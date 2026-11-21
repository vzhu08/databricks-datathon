'use client';
import { useState } from 'react';
import {
  Status,
  Skeleton,
  ResultsTable,
  SourceViewer,
  EditableResult,
  Comparison,
  JobProgress,
  StreamingChat,
  FileUpload,
} from '../../../../packages/ui/src/index';
import { DataChart, ScenarioExplorer } from '../../../../modules/analytics/src/components';
import { GeoMap } from '../../../../modules/maps/src/components';
import { sampleLocations, sampleRoute, toGeoJSON } from '../../../../modules/maps/src/index';
export default function Gallery() {
  const [state, setState] = useState<'empty' | 'loading' | 'error'>('empty'),
    [value, setValue] = useState('A reviewed result'),
    [progress, setProgress] = useState(0.42);
  const rows = [
    { id: '1', name: 'Community garden', status: 'Reviewed', score: 92 },
    { id: '2', name: 'Repair cafe', status: 'Needs review', score: 81 },
    { id: '3', name: 'Reading circle', status: 'Reviewed', score: 76 },
    { id: '4', name: 'Tool library', status: 'New', score: 88 },
    { id: '5', name: 'Art exchange', status: 'New', score: 67 },
    { id: '6', name: 'Seed swap', status: 'Reviewed', score: 85 },
  ];
  return (
    <div className="gallery">
      <div className="page-heading">
        <div>
          <p className="eyebrow">PATTERN GALLERY / DEVELOPMENT ONLY</p>
          <h1>
            The details that
            <br />
            make a tool <em>usable.</em>
          </h1>
          <p>Explore normal, loading, empty, and failure states with local synthetic data.</p>
        </div>
        <span className="badge">Interactive component examples</span>
      </div>
      <div className="gallery-grid">
        <section className="panel">
          <h2>States & recovery</h2>
          <div className="gallery-controls">
            {(['empty', 'loading', 'error'] as const).map((s) => (
              <button
                className={state === s ? '' : 'secondary'}
                key={s}
                onClick={() => setState(s)}
              >
                {s}
              </button>
            ))}
          </div>
          {state === 'loading' ? (
            <Skeleton lines={4} />
          ) : (
            <Status
              kind={state}
              title={state === 'error' ? 'That request did not finish.' : 'Nothing here just yet.'}
              onRetry={state === 'error' ? () => setState('empty') : undefined}
            >
              {state === 'error'
                ? 'Your input is preserved. Retry when you’re ready.'
                : 'Add a source to see the first result.'}
            </Status>
          )}
        </section>
        <section className="panel">
          <h2>Review & revise</h2>
          <p className="panel-note">
            Human edits remain explicit. Empty values fail validation; cancel preserves the previous
            value.
          </p>
          <EditableResult value={value} onSave={setValue} />
          <div className="divider" />
          <Comparison before={42} after={68} unit="points" />
        </section>
        <section className="panel wide">
          <h2>Results you can work with</h2>
          <ResultsTable
            rows={rows}
            columns={[
              { key: 'name', label: 'Project' },
              { key: 'status', label: 'Status' },
              { key: 'score', label: 'Score' },
            ]}
            pageSize={3}
          />
        </section>
        <section className="panel">
          <h2>Evidence in context</h2>
          <SourceViewer
            text="The team will deliver a working demo by Friday. All public paths must be accessible. Evaluate the result with representative user tasks."
            selection={{ start: 47, end: 83 }}
          />
        </section>
        <section className="panel">
          <h2>Progress with control</h2>
          <label>
            Gallery progress
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={progress}
              onChange={(e) => setProgress(Number(e.target.value))}
            />
          </label>
          <JobProgress
            state={progress === 1 ? 'succeeded' : 'running'}
            progress={progress}
            onCancel={() => setProgress(0)}
          />
        </section>
        <section className="panel">
          <h2>Upload & retry</h2>
          <FileUpload
            accept=".txt,.md"
            maxBytes={100000}
            onUpload={async (file, signal, onProgress) => {
              for (let i = 1; i <= 4; i++) {
                signal.throwIfAborted();
                await new Promise((r) => setTimeout(r, 200));
                onProgress(i / 4);
              }
              if (file.name.includes('fail'))
                throw new Error('Gallery failure: rename the file and retry.');
            }}
          />
          <p className="panel-note">
            Gallery-only simulated progress. A filename containing “fail” exercises failure
            recovery. No data leaves this browser.
          </p>
        </section>
        <section className="panel">
          <h2>Streaming, visibly labeled</h2>
          <span className="badge">Fixture output</span>
          <StreamingChat
            stream={async function* (prompt, signal) {
              for (const token of `Fixture response for “${prompt}”. Attach a real server adapter for generated answers.`.split(
                /(?<=\s)/,
              )) {
                signal.throwIfAborted();
                yield token;
                await new Promise((r) => setTimeout(r, 50));
              }
            }}
            suggestions={['Explain the selected source']}
          />
        </section>
        <section className="panel">
          <DataChart
            title="Synthetic weekly participation"
            kind="line"
            unit="people"
            data={[
              { label: 'Week 1', value: 12 },
              { label: 'Week 2', value: 18 },
              { label: 'Week 3', value: 16 },
              { label: 'Week 4', value: 27 },
            ]}
          />
        </section>
        <section className="panel">
          <h2>Local geography</h2>
          <GeoMap
            data={toGeoJSON(sampleLocations, sampleRoute)}
            mode="fixture"
            attribution="Synthetic sample locations; no live tiles or routing"
          />
          <p className="panel-note">
            Approximate display. A route fixture is never labeled as current travel guidance.
          </p>
        </section>
        <section className="panel wide">
          <ScenarioExplorer />
        </section>
      </div>
    </div>
  );
}
