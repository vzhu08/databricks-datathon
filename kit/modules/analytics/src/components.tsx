'use client';
import { useState } from 'react';
import {
  compareScenarios,
  sampleAllocation,
  type AllocationProblem,
  type ChartDatum,
} from './index';
export function DataChart({
  data,
  title,
  kind = 'bar',
  unit = '',
}: {
  data: ChartDatum[];
  title: string;
  kind?: 'bar' | 'line';
  unit?: string;
}) {
  if (!data.length) return <p>{title}: no data available.</p>;
  if (data.some((d) => !Number.isFinite(d.value)))
    return <p role="alert">Chart contains an invalid number.</p>;
  const min = Math.min(0, ...data.map((d) => d.value)),
    max = Math.max(0, ...data.map((d) => d.value));
  const y = (n: number) => 170 - ((n - min) / (max - min || 1)) * 140;
  const x = (i: number) => 50 + ((i + 0.5) / data.length) * 500;
  return (
    <figure>
      <figcaption>
        {title} {unit && `(${unit})`}
      </figcaption>
      <svg
        viewBox="0 0 600 230"
        role="img"
        aria-label={`${title}: ${data.map((d) => `${d.label} ${d.value} ${unit}`).join(', ')}`}
        style={{ width: '100%' }}
      >
        <line x1="40" x2="565" y1={y(0)} y2={y(0)} stroke="currentColor" />
        {kind === 'line' && (
          <polyline
            points={data.map((d, i) => `${x(i)},${y(d.value)}`).join(' ')}
            stroke="#267c72"
            fill="none"
            strokeWidth="3"
          />
        )}
        {data.map((d, i) => (
          <g key={`${d.label}:${i}`}>
            {kind === 'bar' ? (
              <rect
                x={x(i) - 140 / data.length}
                y={Math.min(y(0), y(d.value))}
                width={280 / data.length}
                height={Math.max(1, Math.abs(y(0) - y(d.value)))}
                fill="#267c72"
              />
            ) : (
              <circle cx={x(i)} cy={y(d.value)} r="4" fill="#267c72" />
            )}
            <text
              x={x(i)}
              y={d.value < 0 ? y(d.value) + 15 : y(d.value) - 8}
              textAnchor="middle"
              fontSize="12"
            >
              {d.value}
            </text>
            <text x={x(i)} y="210" textAnchor="middle" fontSize="11">
              {d.label}
            </text>
          </g>
        ))}
      </svg>
    </figure>
  );
}
export function ScenarioExplorer({ problem = sampleAllocation }: { problem?: AllocationProblem }) {
  const [budget, setBudget] = useState(problem.budget);
  const { before, after, valueDelta } = compareScenarios(problem, budget);
  return (
    <section aria-label="Allocation what-if scenario">
      <h3>Allocate a sample event budget</h3>
      <p>
        Synthetic units: budget credits and estimated benefit points. The slider reruns the same
        exact constraint solver used by the API.
      </p>
      <label>
        Budget: {budget} credits{' '}
        <input
          type="range"
          min="0"
          max={Math.max(200, problem.budget * 2)}
          step="5"
          value={budget}
          onChange={(e) => setBudget(Number(e.target.value))}
        />
      </label>
      <div aria-live="polite">
        {after.status === 'infeasible' ? (
          <p role="status">Infeasible: {after.reason}</p>
        ) : (
          <>
            <p>
              Benefit {after.value} points · cost {after.cost} credits · {after.remaining} credits
              unused
            </p>
            <ul>
              {after.selected.map((item) => (
                <li key={item.id}>
                  {item.label}: {item.cost} credits / {item.value} benefit
                </li>
              ))}
            </ul>
          </>
        )}
        <p>
          Baseline: {before.status === 'optimal' ? `${before.value} points` : 'infeasible'} ·
          Change:{' '}
          {valueDelta === null
            ? 'not comparable'
            : `${valueDelta >= 0 ? '+' : ''}${valueDelta} points`}
        </p>
      </div>
      <DataChart
        title="Benefit comparison"
        unit="points"
        data={[
          ...(before.status === 'optimal' ? [{ label: 'Before', value: before.value }] : []),
          ...(after.status === 'optimal' ? [{ label: 'After', value: after.value }] : []),
        ]}
      />
    </section>
  );
}
