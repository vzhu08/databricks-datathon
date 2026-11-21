'use client';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

export function Status({
  kind = 'empty',
  title,
  children,
  onRetry,
}: {
  kind?: 'empty' | 'loading' | 'error';
  title: string;
  children?: ReactNode;
  onRetry?: () => void;
}) {
  return (
    <div className={`kit-status kit-status-${kind}`} role={kind === 'error' ? 'alert' : 'status'}>
      <span className="kit-status-icon" aria-hidden>
        {kind === 'loading' ? '◌' : kind === 'error' ? '!' : '✳'}
      </span>
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {onRetry && (
        <button className="secondary" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}
export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div aria-label="Loading" role="status" className="kit-skeleton">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} style={{ width: `${100 - i * 12}%` }} />
      ))}
    </div>
  );
}
export function FileUpload({
  accept = '.txt,.md,.csv,.pdf,.docx',
  maxBytes = 10_000_000,
  onUpload,
}: {
  accept?: string;
  maxBytes?: number;
  onUpload: (
    file: File,
    signal: AbortSignal,
    onProgress: (fraction: number) => void,
  ) => Promise<void>;
}) {
  const [file, setFile] = useState<File | null>(null),
    [error, setError] = useState(''),
    [progress, setProgress] = useState(0),
    [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const serial = useRef(0);
  useEffect(
    () => () => {
      controller.current?.abort();
    },
    [],
  );
  async function upload(f: File) {
    const seq = ++serial.current;
    controller.current?.abort();
    const c = new AbortController();
    controller.current = c;
    setFile(f);
    setError('');
    setProgress(0);
    if (f.size > maxBytes) {
      setError(`File exceeds ${(maxBytes / 1e6).toFixed(0)} MB.`);
      setBusy(false);
      return;
    }
    const allowed = accept.split(',').map((a) => a.trim().toLowerCase());
    if (
      !allowed.some((a) =>
        a.startsWith('.')
          ? f.name.toLowerCase().endsWith(a)
          : a.endsWith('/*')
            ? f.type.startsWith(a.slice(0, -1))
            : f.type === a,
      )
    ) {
      setError('Unsupported file type. Choose one of the listed formats.');
      setBusy(false);
      return;
    }
    setBusy(true);
    try {
      await onUpload(f, c.signal, (n) => {
        if (seq === serial.current) setProgress(Math.max(0, Math.min(1, n)));
      });
      if (seq === serial.current) setProgress(1);
    } catch (e) {
      if (seq === serial.current && !c.signal.aborted)
        setError(e instanceof Error ? e.message : 'Upload failed');
    } finally {
      if (seq === serial.current) setBusy(false);
    }
  }
  return (
    <div className="kit-upload">
      <label className="kit-drop">
        <span aria-hidden>↥</span>
        <strong>Choose a document</strong>
        <small>
          {accept} · up to {(maxBytes / 1e6).toFixed(0)} MB
        </small>
        <input
          aria-label="Upload document"
          type="file"
          accept={accept}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void upload(f);
            e.target.value = '';
          }}
        />
      </label>
      {file && (
        <p className="kit-file">
          {file.name} <span>{(file.size / 1024).toFixed(1)} KB</span>
        </p>
      )}
      {busy && (
        <>
          <progress aria-label="Upload progress" max={1} value={progress} />
          <button
            className="secondary"
            onClick={() => {
              serial.current++;
              controller.current?.abort();
              setBusy(false);
              setError('Upload cancelled.');
            }}
          >
            Cancel
          </button>
        </>
      )}
      {error && (
        <Status kind="error" title={error} onRetry={file ? () => void upload(file) : undefined} />
      )}
    </div>
  );
}
export type TableColumn<T> = {
  key: keyof T;
  label: string;
  render?: (value: T[keyof T], row: T) => ReactNode;
};
export function ResultsTable<T extends { id: string }>({
  rows,
  columns,
  pageSize = 5,
  onExport,
}: {
  rows: T[];
  columns: TableColumn<T>[];
  pageSize?: number;
  onExport?: () => void;
}) {
  const [query, setQuery] = useState(''),
    [sort, setSort] = useState<{ key: keyof T; direction: 1 | -1 } | null>(null),
    [page, setPage] = useState(1);
  const filtered = useMemo(
    () =>
      rows
        .filter((r) =>
          columns.some((c) =>
            String(r[c.key] ?? '')
              .toLowerCase()
              .includes(query.toLowerCase()),
          ),
        )
        .sort((a, b) => {
          if (!sort) return 0;
          const x = a[sort.key],
            y = b[sort.key];
          return (
            (typeof x === 'number' && typeof y === 'number'
              ? x - y
              : String(x).localeCompare(String(y))) * sort.direction
          );
        }),
    [rows, columns, query, sort],
  );
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize)),
    current = Math.min(page, pages);
  return (
    <div className="kit-table">
      <div className="kit-toolbar">
        <input
          aria-label="Filter results"
          placeholder="Filter results…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(1);
          }}
        />
        {onExport && (
          <button className="secondary" onClick={onExport}>
            Export CSV ↗
          </button>
        )}
      </div>
      {filtered.length ? (
        <>
          <div className="kit-table-scroll">
            <table>
              <thead>
                <tr>
                  {columns.map((c) => (
                    <th
                      key={String(c.key)}
                      aria-sort={
                        sort?.key === c.key
                          ? sort.direction === 1
                            ? 'ascending'
                            : 'descending'
                          : 'none'
                      }
                    >
                      <button
                        onClick={() =>
                          setSort({
                            key: c.key,
                            direction: sort?.key === c.key && sort.direction === 1 ? -1 : 1,
                          })
                        }
                      >
                        {c.label} ↕
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.slice((current - 1) * pageSize, current * pageSize).map((row) => (
                  <tr key={row.id}>
                    {columns.map((c) => (
                      <td key={String(c.key)}>
                        {c.render ? c.render(row[c.key], row) : String(row[c.key] ?? '—')}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="kit-pagination">
            <span>
              {filtered.length} results · Page {current} of {pages}
            </span>
            <button
              className="secondary"
              disabled={current === 1}
              onClick={() => setPage(current - 1)}
            >
              Previous
            </button>
            <button
              className="secondary"
              disabled={current === pages}
              onClick={() => setPage(current + 1)}
            >
              Next
            </button>
          </div>
        </>
      ) : (
        <Status title="No matching results">Try a different filter or add a sample.</Status>
      )}
    </div>
  );
}
export function SourceViewer({
  text,
  selection,
}: {
  text: string;
  selection?: { start: number; end: number };
}) {
  const valid =
    selection &&
    Number.isInteger(selection.start) &&
    selection.start >= 0 &&
    selection.end > selection.start &&
    selection.end <= text.length;
  return (
    <pre className="kit-source" aria-label="Source document">
      {valid ? (
        <>
          {text.slice(0, selection.start)}
          <mark>{text.slice(selection.start, selection.end)}</mark>
          {text.slice(selection.end)}
        </>
      ) : (
        text || 'This source contains no text.'
      )}
    </pre>
  );
}
export function EditableResult({
  value,
  onSave,
  emptyLabel = 'Missing',
  validate = (s) => (s.trim() ? null : 'A value is required.'),
}: {
  value: string;
  emptyLabel?: string;
  onSave: (value: string) => void | Promise<void>;
  validate?: (value: string) => string | null;
}) {
  const [editing, setEditing] = useState(false),
    [draft, setDraft] = useState(value),
    [error, setError] = useState('');
  return (
    <div className="kit-edit">
      {editing ? (
        <>
          <label>
            Reviewed value
            <input value={draft} onChange={(e) => setDraft(e.target.value)} />
          </label>
          {error && <p role="alert">{error}</p>}
          <div className="kit-actions">
            <button
              onClick={async () => {
                const issue = validate(draft);
                if (issue) {
                  setError(issue);
                  return;
                }
                try {
                  await onSave(draft);
                  setEditing(false);
                  setError('');
                } catch (e) {
                  setError(e instanceof Error ? e.message : 'Could not save this value.');
                }
              }}
            >
              Save review
            </button>
            <button
              className="secondary"
              onClick={() => {
                setDraft(value);
                setEditing(false);
                setError('');
              }}
            >
              Cancel
            </button>
          </div>
        </>
      ) : (
        <>
          <span>{value || emptyLabel}</span>
          <button
            className="secondary"
            onClick={() => {
              setDraft(value);
              setEditing(true);
            }}
          >
            Edit
          </button>
        </>
      )}
    </div>
  );
}
export function JobProgress({
  state,
  progress,
  onCancel,
}: {
  state: string;
  progress: number;
  onCancel?: () => void;
}) {
  return (
    <div className="kit-job" aria-live="polite">
      <div>
        <strong>{state}</strong>
        <span>{Math.round(progress * 100)}%</span>
      </div>
      <progress aria-label="Job progress" value={Math.max(0, Math.min(1, progress))} max={1} />
      {onCancel && ['queued', 'running'].includes(state) && (
        <button className="secondary" onClick={onCancel}>
          Cancel job
        </button>
      )}
    </div>
  );
}
export function Comparison({
  before,
  after,
  unit = '',
}: {
  before: number;
  after: number;
  unit?: string;
}) {
  const difference = after - before;
  return (
    <div className="kit-comparison">
      <div>
        <small>Before</small>
        <strong>
          {before.toLocaleString()} {unit}
        </strong>
      </div>
      <span aria-hidden>→</span>
      <div>
        <small>After</small>
        <strong>
          {after.toLocaleString()} {unit}
        </strong>
      </div>
      <span className="badge">
        {difference > 0 ? '+' : ''}
        {difference.toLocaleString()} {unit}
      </span>
    </div>
  );
}
export function MetricCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: string | number;
  detail?: string;
}) {
  return (
    <article className="kit-metric">
      <p>{label}</p>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
    </article>
  );
}
export function StreamingChat({
  stream,
  citations = [],
  suggestions = [],
}: {
  stream: (prompt: string, signal: AbortSignal) => AsyncIterable<string>;
  citations?: { label: string; onOpen: () => void }[];
  suggestions?: string[];
}) {
  const [input, setInput] = useState(''),
    [output, setOutput] = useState(''),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function send(prompt: string) {
    if (!prompt.trim()) return;
    const c = new AbortController();
    controller.current?.abort();
    controller.current = c;
    setBusy(true);
    setOutput('');
    setError('');
    try {
      for await (const part of stream(prompt, c.signal)) {
        if (c.signal.aborted) break;
        setOutput((s) => s + part);
      }
    } catch (e) {
      if (!c.signal.aborted) setError(e instanceof Error ? e.message : 'Stream failed');
    } finally {
      if (controller.current === c) setBusy(false);
    }
  }
  return (
    <div className="kit-chat">
      <label>
        Ask about your sources
        <input value={input} onChange={(e) => setInput(e.target.value)} />
      </label>
      <div className="kit-actions">
        <button disabled={busy || !input.trim()} onClick={() => void send(input)}>
          Send ↗
        </button>
        {busy && (
          <button
            className="secondary"
            onClick={() => {
              controller.current?.abort();
              setBusy(false);
            }}
          >
            Stop
          </button>
        )}
      </div>
      {output && (
        <p className="kit-chat-output" aria-live="polite">
          {output}
        </p>
      )}
      {error && <Status kind="error" title={error} onRetry={() => void send(input)} />}
      <div className="kit-actions">
        {citations.map((c, i) => (
          <button className="secondary" key={i} onClick={c.onOpen}>
            {c.label}
          </button>
        ))}
        {suggestions.map((s) => (
          <button
            className="secondary"
            disabled={busy}
            key={s}
            onClick={() => {
              setInput(s);
              void send(s);
            }}
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
