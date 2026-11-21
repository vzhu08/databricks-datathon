'use client';
import { useState } from 'react';
import { normalizeText } from '../../modules/documents/src/index';
import { LocalIndex, answerFromResults } from '../../modules/retrieval/src/index';
import { extractFields, reviewExtraction } from '../../modules/extraction/src/index';
import { toCSV } from '../../modules/exports/src/index';
import {
  DocumentSchema,
  type NormalizedDocument,
  type Citation,
} from '../../packages/contracts/src/index';
import {
  FileUpload,
  SourceViewer,
  EditableResult,
  Status,
  MetricCard,
  StreamingChat,
} from '../../packages/ui/src/index';
import { reviewedReport } from './model';
import { sampleText } from './sample';
const sample = () => normalizeText({ filename: 'community-garden.txt', text: sampleText });
function download(data: Blob, name: string) {
  const url = URL.createObjectURL(data);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export default function DocumentWorkbench() {
  const [doc, setDoc] = useState<NormalizedDocument>(() => sample()),
    [extraction, setExtraction] = useState(() => extractFields(sample())),
    [selected, setSelected] = useState<Citation>(),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false),
    [retrieved, setRetrieved] = useState<Citation[]>([]),
    [share, setShare] = useState('');
  function open(d: NormalizedDocument) {
    setDoc(d);
    setExtraction(extractFields(d));
    setSelected(undefined);
    setRetrieved([]);
    setShare('');
    setError('');
  }
  const { rows, report: reportData } = reviewedReport(doc, extraction);
  async function report() {
    setBusy(true);
    setError('');
    try {
      const response = await fetch('/api/kit/report', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(reportData),
      });
      if (!response.ok) throw new Error((await response.json()).error?.message ?? 'Export failed');
      download(await response.blob(), 'document-report.pdf');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Export failed');
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="composition">
      <div className="page-heading">
        <div>
          <p className="eyebrow">REFERENCE / DOCUMENT WORKBENCH</p>
          <h1>
            From document
            <br />
            to <em>understanding.</em>
          </h1>
          <p>Extract the details. Follow the evidence. Make the result your own.</p>
        </div>
        <span className="badge">Local algorithms · synthetic sample</span>
      </div>
      <div className="metrics">
        <MetricCard
          label="Source"
          value={doc.filename}
          detail="Normalized with retained provenance"
        />
        <MetricCard
          label="Fields with evidence"
          value={extraction.fields.filter((f) => f.status === 'found').length}
          detail={`${extraction.fields.length} configured fields`}
        />
        <MetricCard
          label="Characters"
          value={doc.text.length.toLocaleString()}
          detail="Offsets retained through extraction"
        />
      </div>
      <div className="composition-grid">
        <section className="panel">
          <div className="panel-heading">
            <h2>Your sources</h2>
            <button className="secondary" onClick={() => open(sample())}>
              Reset sample
            </button>
          </div>
          <FileUpload
            accept=".txt,.md,.csv,.pdf,.docx,.png,.jpg,.jpeg"
            onUpload={async (file, signal, progress) => {
              progress(0.1);
              const response = await fetch('/api/kit/documents', {
                method: 'POST',
                headers: { 'x-filename': encodeURIComponent(file.name) },
                body: file,
                signal,
              });
              progress(0.8);
              const value = await response.json();
              if (!response.ok) throw new Error(value.error?.message ?? 'Could not parse file');
              open(DocumentSchema.parse(value));
            }}
          />
          <h3 className="subhead">
            {selected ? 'Highlighted supporting passage' : 'Source preview'}
          </h3>
          <SourceViewer text={doc.text} selection={selected} />
        </section>
        <section className="panel">
          <div className="panel-heading">
            <h2>A reviewable result</h2>
            <span className="badge">Evidence first</span>
          </div>
          <p className="panel-note">
            Local labeled-field extraction. Ambiguous and missing values remain visible. Edits are
            marked as human review.
          </p>
          <div className="field-list">
            {extraction.fields.map((f) => (
              <article key={`${doc.id}:${doc.hash}:${f.key}`}>
                <div className="field-label">
                  <strong>{f.label}</strong>
                  <span className={`field-state state-${f.status}`}>{f.status}</span>
                </div>
                <EditableResult
                  emptyLabel={f.status === 'ambiguous' ? 'Review the candidates below' : 'Missing'}
                  value={String(f.value ?? '')}
                  onSave={(value) => {
                    const reviewed = reviewExtraction(
                      extraction,
                      {
                        key: f.key,
                        value,
                        editor: 'local-reviewer',
                        note: 'Reviewed in workbench',
                      },
                      doc,
                    );
                    setExtraction(reviewed);
                    setError('');
                  }}
                />
                {f.review && (
                  <p className="review-note">
                    {f.review.supported
                      ? 'Human reviewed · matches original source'
                      : 'Human reviewed · not supported by original source'}
                  </p>
                )}
                {f.candidates.map((c, i) => (
                  <button className="evidence-link" key={i} onClick={() => setSelected(c.evidence)}>
                    ↗ Inspect source {i + 1}
                  </button>
                ))}
                {f.issues.length > 0 && <small className="panel-note">{f.issues.join(' ')}</small>}
              </article>
            ))}
          </div>
          <div className="kit-actions">
            <button disabled={busy} onClick={() => void report()}>
              {busy ? 'Preparing…' : 'Download report'} ↓
            </button>
            <button
              className="secondary"
              onClick={() => download(new Blob([toCSV(rows)], { type: 'text/csv' }), 'fields.csv')}
            >
              Export CSV
            </button>
          </div>
          <div className="divider" />
          <p className="panel-note">
            Deliberately share this summary and its quoted evidence with anyone who has the link on
            this local server. It expires in 1 hour and can be revoked.
          </p>
          <button
            className="secondary"
            onClick={async () => {
              setError('');
              try {
                const response = await fetch('/api/kit/share', {
                  method: 'POST',
                  headers: { 'content-type': 'application/json' },
                  body: JSON.stringify({ ...reportData, confirmed: true }),
                });
                const value = await response.json();
                if (!response.ok) throw new Error(value.error?.message ?? 'Share failed');
                setShare(value.url);
              } catch (e) {
                setError(e instanceof Error ? e.message : 'Share failed');
              }
            }}
          >
            Create local share link
          </button>
          {share && (
            <div className="kit-actions">
              <a href={share} target="_blank" rel="noreferrer">
                Open shared report ↗
              </a>
              <button
                className="secondary"
                onClick={async () => {
                  const response = await fetch(share, { method: 'DELETE' });
                  if (response.ok) setShare('');
                  else setError('Could not revoke link.');
                }}
              >
                Revoke link
              </button>
            </div>
          )}
          {error && <Status kind="error" title={error} onRetry={() => void report()} />}
        </section>
      </div>
      <section className="panel">
        <h2>Ask the source</h2>
        <p className="panel-note">
          Deterministic retrieval: returns matching passages with validated citations. No model
          call.
        </p>
        <StreamingChat
          key={`${doc.id}:${doc.hash}`}
          stream={async function* (query, signal) {
            const index = new LocalIndex();
            index.upsert(doc);
            const results = index.search(query);
            const answer = answerFromResults(query, results, [doc]);
            setRetrieved(answer.citations);
            const text = answer.answer;
            for (const word of text.split(/(?<=\s)/)) {
              if (signal.aborted) return;
              yield word;
              await new Promise((resolve) => setTimeout(resolve, 12));
            }
          }}
          suggestions={['What is the budget?', 'What is the requirement?']}
          citations={retrieved.map((citation, i) => ({
            label: `Source ${i + 1}: ${citation.label ?? doc.filename}`,
            onOpen: () => setSelected(citation),
          }))}
        />
      </section>
    </div>
  );
}
