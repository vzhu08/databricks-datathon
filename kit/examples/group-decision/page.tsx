'use client';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  rankCandidates,
  sampleCandidates,
  samplePreferences,
  type Preference,
} from '../../modules/recommendations/src/index';
import { RoomClient } from '../../modules/realtime/src/browser';
import { MetricCard, Status } from '../../packages/ui/src/index';
export default function GroupDecision() {
  const [budget, setBudget] = useState(25),
    [accessible, setAccessible] = useState(true),
    [costWeight, setCostWeight] = useState(2),
    [voter, setVoter] = useState('alex'),
    [votes, setVotes] = useState<Record<string, string>>({}),
    [realtime, setRealtime] = useState(false),
    [status, setStatus] = useState('Local session'),
    [room, setRoom] = useState('demo-garden'),
    [url, setUrl] = useState('ws://127.0.0.1:8788');
  const client = useRef<RoomClient | null>(null);
  const preferences: Preference[] = useMemo(
    () =>
      samplePreferences.map((p, i) =>
        i === 0
          ? {
              ...p,
              requiredTags: accessible ? ['accessible'] : [],
              bounds: { cost: { max: budget } },
              weights: { ...p.weights, cost: { weight: costWeight, direction: 'lower' as const } },
            }
          : p,
      ),
    [budget, accessible, costWeight],
  );
  const result = useMemo(
    () =>
      rankCandidates(
        sampleCandidates,
        preferences,
        Object.entries(votes)
          .filter(
            ([m, c]) =>
              preferences.some((p) => p.memberId === m) && sampleCandidates.some((s) => s.id === c),
          )
          .map(([memberId, candidateId]) => ({ memberId, candidateId })),
      ),
    [preferences, votes],
  );
  useEffect(() => {
    if (!realtime) return;
    let c: RoomClient;
    try {
      c = new RoomClient({
        url,
        room,
        userId: voter,
        onStatus: (state, message) => setStatus(message ?? state),
      });
    } catch (e) {
      setStatus(e instanceof Error ? e.message : 'Invalid connection');
      return;
    }
    client.current = c;
    const unsubscribe = c.onState((s) => setVotes(s.votes));
    c.connect();
    return () => {
      unsubscribe();
      c.close();
      client.current = null;
    };
  }, [realtime, url, room, voter]);
  const winner = result.ranked[0];
  return (
    <div className="composition">
      <div className="page-heading">
        <div>
          <p className="eyebrow">REFERENCE / GROUP DECISIONS</p>
          <h1>
            A choice that works
            <br />
            for <em>everyone.</em>
          </h1>
          <p>Hard constraints first. Explainable preferences next. Every vote visible.</p>
        </div>
        <span className="badge">
          {realtime ? 'Local WebSocket room' : 'Local session'} · synthetic activities
        </span>
      </div>
      <div className="metrics">
        <MetricCard
          label="Eligible choices"
          value={result.ranked.length}
          detail={`${result.excluded.length} excluded by hard constraints`}
        />
        <MetricCard
          label="Leading choice"
          value={winner?.candidate.name ?? 'None'}
          detail="Score → votes → stable ID"
        />
        <MetricCard
          label="Votes cast"
          value={Object.keys(votes).length}
          detail="One current vote per member"
        />
      </div>
      <div className="composition-grid group-grid">
        <section className="panel">
          <h2>What matters to your group?</h2>
          <p className="panel-note">
            Alex’s preferences below; Sam prefers outdoors and a short trip. Both members have equal
            weight.
          </p>
          <label>
            Maximum cost per person: ${budget}
            <input
              aria-label="Maximum cost"
              type="range"
              min={0}
              max={50}
              value={budget}
              onChange={(e) => setBudget(Number(e.target.value))}
            />
          </label>
          <label className="check-label">
            <input
              type="checkbox"
              checked={accessible}
              onChange={(e) => setAccessible(e.target.checked)}
            />
            Accessible venue required
          </label>
          <label>
            Cost preference weight: {costWeight}
            <input
              aria-label="Cost preference weight"
              type="range"
              min={0}
              max={5}
              value={costWeight}
              onChange={(e) => setCostWeight(Number(e.target.value))}
            />
          </label>
          <div className="divider" />
          <label>
            Voting as
            <select value={voter} onChange={(e) => setVoter(e.target.value)}>
              <option value="alex">Alex</option>
              <option value="sam">Sam</option>
            </select>
          </label>
          <details>
            <summary>Connect a second browser</summary>
            <p className="panel-note">
              Start the local room server with npm run realtime. Open this page in a second browser
              and choose a different member. Session rooms use memory; restart clears state.
            </p>
            <label>
              WebSocket server
              <input value={url} onChange={(e) => setUrl(e.target.value)} />
            </label>
            <label>
              Room
              <input value={room} onChange={(e) => setRoom(e.target.value)} />
            </label>
            <button
              className="secondary"
              onClick={() => {
                setRealtime(!realtime);
                if (realtime) setStatus('Local session');
              }}
            >
              {realtime ? 'Disconnect' : 'Connect room'}
            </button>
            <p role="status">{status}</p>
          </details>
          <button
            className="text-button"
            onClick={() => {
              setVotes({});
              setBudget(25);
              setAccessible(true);
              setCostWeight(2);
              setRealtime(false);
            }}
          >
            Reset local sample
          </button>
        </section>
        <section className="panel">
          <div className="panel-heading">
            <h2>Find your common ground</h2>
            <span className="badge">{result.ranked.length} possibilities</span>
          </div>
          {result.ranked.length ? (
            result.ranked.map((r, i) => (
              <article className="choice-card" key={r.candidate.id}>
                <div className="choice-top">
                  <span className="rank">{String(i + 1).padStart(2, '0')}</span>
                  <div>
                    <h3>{r.candidate.name}</h3>
                    <p>
                      ${r.candidate.metrics.cost} per person · {r.candidate.metrics.minutes} minutes
                      away
                    </p>
                  </div>
                  <strong className="score">
                    {Math.round(r.score * 100)}
                    <small>/ 100</small>
                  </strong>
                </div>
                <div className="tag-row">
                  {r.candidate.tags.map((t) => (
                    <span className="badge" key={t}>
                      {t}
                    </span>
                  ))}
                </div>
                <details>
                  <summary>Why this score?</summary>
                  {r.explanations.map((e, j) => (
                    <p className="panel-note" key={j}>
                      {e.memberId} · {e.input}: {e.value}. {e.note}. Contribution{' '}
                      {e.contribution.toFixed(2)}.
                    </p>
                  ))}
                </details>
                <div className="choice-bottom">
                  <span>
                    {r.votes} {r.votes === 1 ? 'vote' : 'votes'}
                    {votes[voter] === r.candidate.id ? ' · Your choice' : ''}
                  </span>
                  <button
                    className={votes[voter] === r.candidate.id ? '' : 'secondary'}
                    onClick={() => {
                      if (realtime && client.current) client.current.vote(r.candidate.id);
                      else setVotes((v) => ({ ...v, [voter]: r.candidate.id }));
                    }}
                    aria-label={`Vote for ${r.candidate.name}`}
                  >
                    {votes[voter] === r.candidate.id ? 'Voted ✓' : 'Vote for this'}
                  </button>
                </div>
              </article>
            ))
          ) : (
            <Status title="No choice meets every constraint">
              Increase the budget or review the group’s required constraints. We never quietly relax
              them.
            </Status>
          )}
          {result.excluded.length > 0 && (
            <details className="excluded">
              <summary>
                {result.excluded.length} excluded{' '}
                {result.excluded.length === 1 ? 'choice' : 'choices'}
              </summary>
              {result.excluded.map((e) => (
                <p className="panel-note" key={e.id}>
                  {sampleCandidates.find((c) => c.id === e.id)?.name}: {e.reasons.join('; ')}
                </p>
              ))}
            </details>
          )}
        </section>
      </div>
    </div>
  );
}
