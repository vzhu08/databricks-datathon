'use client';

import { useEffect, useId, useState, useSyncExternalStore, type FormEvent } from 'react';
import type { Note } from '../../src/index';
import { createNotesController, type NotesController } from './controller';
import {
  createFixtureSession,
  createLiveSession,
  fixtureAccounts,
  fixturePassword,
} from './session';
import './demo.css';

function NoteEditor({
  note,
  controller,
  busy,
}: {
  note: Note;
  controller: NotesController;
  busy: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(note.title);
  const [body, setBody] = useState(note.body);
  const id = useId();
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (await controller.update(note.id, { title, body })) setEditing(false);
  }
  return (
    <li className="notes-card">
      {editing ? (
        <form onSubmit={save}>
          <label htmlFor={`${id}-title`}>Edit title</label>
          <input
            id={`${id}-title`}
            required
            maxLength={200}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            disabled={busy}
          />
          <label htmlFor={`${id}-body`}>Edit body</label>
          <textarea
            id={`${id}-body`}
            maxLength={50_000}
            value={body}
            onChange={(event) => setBody(event.target.value)}
            disabled={busy}
          />
          <div className="notes-actions">
            <button disabled={busy}>Save changes</button>
            <button type="button" disabled={busy} onClick={() => setEditing(false)}>
              Cancel edit
            </button>
          </div>
        </form>
      ) : (
        <>
          <h3>{note.title}</h3>
          <p className="notes-body">{note.body || 'No body text.'}</p>
          <div className="notes-actions">
            <button
              disabled={busy}
              onClick={() => {
                setTitle(note.title);
                setBody(note.body);
                setEditing(true);
              }}
            >
              Edit {note.title}
            </button>
            <button disabled={busy} onClick={() => void controller.remove(note.id)}>
              Delete {note.title}
            </button>
          </div>
        </>
      )}
    </li>
  );
}

/** Optional example widget; key it by mode if your application changes mode after mount. */
export function AuthNotesDemo({
  mode = 'fixture',
  githubOAuth = false,
}: {
  mode?: 'fixture' | 'live';
  githubOAuth?: boolean;
}) {
  const [session] = useState(() =>
    mode === 'live' ? createLiveSession() : createFixtureSession(),
  );
  const [controller] = useState(() => createNotesController(session));
  const state = useSyncExternalStore(
    controller.subscribe,
    controller.snapshot,
    controller.snapshot,
  );
  const [email, setEmail] = useState(
    mode === 'fixture' ? (fixtureAccounts[0].email as string) : '',
  );
  const [password, setPassword] = useState(mode === 'fixture' ? fixturePassword : '');
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [failure, setFailure] = useState(false);
  const id = useId();
  useEffect(() => {
    void controller.initialize();
    return () => controller.dispose();
  }, [controller]);
  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await controller.signIn(email, password);
    setPassword('');
  }
  async function signOut() {
    if (await controller.signOut()) {
      setTitle('');
      setBody('');
      setPassword('');
    }
  }
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (await controller.create({ title, body })) {
      setTitle('');
      setBody('');
    }
  }
  return (
    <main className="notes-demo" aria-busy={state.busy}>
      <p className="notes-eyebrow">SUPABASE MODULE · {session.mode.toUpperCase()}</p>
      <h1>Your private notes</h1>
      <p>
        {mode === 'fixture'
          ? 'An in-memory demo of the interface. No Supabase connection; reloading clears all notes.'
          : 'Live Supabase authentication and database access through server routes. Each account sees its own notes.'}
      </p>
      {mode === 'fixture' ? (
        <details className="notes-fixtures">
          <summary>Fixture accounts and failure controls</summary>
          <p>
            Use {fixtureAccounts.map((account) => account.email).join(' or ')} with password{' '}
            <code>{fixturePassword}</code>. Switch accounts to check isolation.
          </p>
          <label>
            <input
              type="checkbox"
              checked={failure}
              disabled={state.busy}
              onChange={(event) => {
                setFailure(event.target.checked);
                session.setFailure?.(event.target.checked);
              }}
            />{' '}
            Simulate request failure
          </label>
        </details>
      ) : null}
      {state.busy || state.phase === 'loading' ? (
        <p role="status">{state.phase === 'loading' ? 'Loading session and notes…' : 'Working…'}</p>
      ) : null}
      {state.error ? (
        <div role="alert" className="notes-error">
          <p>{state.error}</p>
          <button
            disabled={state.busy}
            onClick={() => void (state.user ? controller.reload() : controller.initialize())}
          >
            Retry loading
          </button>
        </div>
      ) : null}
      {state.phase === 'signed-out' ? (
        <form className="notes-card" onSubmit={signIn}>
          <h2>Sign in</h2>
          <label htmlFor={`${id}-email`}>Email</label>
          <input
            id={`${id}-email`}
            type="email"
            autoComplete="username"
            value={email}
            required
            disabled={state.busy}
            onChange={(event) => setEmail(event.target.value)}
          />
          <label htmlFor={`${id}-password`}>Password</label>
          <input
            id={`${id}-password`}
            type="password"
            autoComplete="current-password"
            value={password}
            required
            disabled={state.busy}
            onChange={(event) => setPassword(event.target.value)}
          />
          <button disabled={state.busy}>Sign in</button>
          {mode === 'live' && githubOAuth ? (
            <p>
              <a href="/api/auth?action=oauth">Continue with GitHub</a>
            </p>
          ) : null}
        </form>
      ) : null}
      {state.user ? (
        <>
          <div className="notes-session">
            <p>
              Signed in as <strong>{state.user.email ?? state.user.id}</strong>
            </p>
            <button disabled={state.busy} onClick={() => void signOut()}>
              Sign out
            </button>
          </div>
          <form className="notes-card" onSubmit={create}>
            <h2>Create a note</h2>
            <label htmlFor={`${id}-title`}>Title</label>
            <input
              id={`${id}-title`}
              required
              maxLength={200}
              value={title}
              disabled={state.busy}
              onChange={(event) => setTitle(event.target.value)}
            />
            <label htmlFor={`${id}-body`}>Body</label>
            <textarea
              id={`${id}-body`}
              maxLength={50_000}
              value={body}
              disabled={state.busy}
              onChange={(event) => setBody(event.target.value)}
            />
            <button disabled={state.busy || !title.trim()}>Create note</button>
          </form>
          <div className="notes-session">
            <h2>Notes ({state.notes.length})</h2>
            <button disabled={state.busy} onClick={() => void controller.reload()}>
              Refresh notes
            </button>
          </div>
          {!state.notes.length && state.phase === 'ready' && !state.error ? (
            <p className="notes-empty" role="status">
              No notes yet. Create your first note above.
            </p>
          ) : null}
          <ul className="notes-list">
            {state.notes.map((note) => (
              <NoteEditor key={note.id} note={note} controller={controller} busy={state.busy} />
            ))}
          </ul>
        </>
      ) : null}
    </main>
  );
}
