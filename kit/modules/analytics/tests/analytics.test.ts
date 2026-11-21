import { describe, expect, it } from 'vitest';
import {
  aggregate,
  cleanCsv,
  compareScenarios,
  optimizeAllocation,
  sampleAllocation,
  sampleCsv,
  scoreRow,
  summarize,
} from '../src/index';
describe('analytics', () => {
  it('handles quotes, missing data and invalid numbers without silently coercing', () => {
    const r = cleanCsv('name,cost\n"one, two",10\nthree,NA\nfour,broken\n', ['cost']);
    expect(r.rows).toEqual([
      { name: 'one, two', cost: 10 },
      { name: 'three', cost: null },
      { name: 'four', cost: null },
    ]);
    expect(r.issues).toHaveLength(1);
    expect(summarize(r.rows.map((x) => x.cost as number | null))).toMatchObject({
      mean: 10,
      missing: 2,
      standardDeviation: 0,
    });
  });
  it('handles empty data and rejects ambiguous headers / oversized input', () => {
    expect(cleanCsv('').rows).toEqual([]);
    expect(summarize([])).toMatchObject({ count: 0, mean: null, median: null });
    expect(() => cleanCsv('a,a\n1,2')).toThrow('unique');
    expect(() => cleanCsv('a\n1', ['b'])).toThrow('does not exist');
    expect(() => cleanCsv('x'.repeat(2_000_001))).toThrow('2 MB');
  });
  it('calculates population stats and categorical/time series totals', () => {
    expect(summarize([1, 2, 3, 4, null])).toMatchObject({
      count: 4,
      missing: 1,
      mean: 2.5,
      median: 2.5,
      min: 1,
      max: 4,
    });
    const r = cleanCsv(sampleCsv, ['cost', 'participants']);
    expect(aggregate(r.rows, 'day', 'participants')).toEqual([
      { label: '2026-01-01', value: 20 },
      { label: '2026-01-02', value: 26 },
    ]);
  });
  it('keeps score explanations consistent with missing inputs', () => {
    const result = scoreRow({ impact: 8, cost: null }, [
      { column: 'impact', min: 0, max: 10, weight: 3, direction: 'higher' },
      { column: 'cost', min: 0, max: 100, weight: 1, direction: 'lower' },
    ]);
    expect(result.score).toBeCloseTo(0.6);
    expect(result.contributions[1].contribution).toBe(0);
  });
  it('solves an actual budget/cardinality/category optimization and applies identical what-if calculations', () => {
    const solution = optimizeAllocation(sampleAllocation);
    expect(solution.status).toBe('optimal');
    expect(solution.selected.map((i) => i.id)).toEqual(['captions', 'mentors', 'signage']);
    expect(solution.cost).toBe(100);
    expect(solution.value).toBe(127);
    const scenario = compareScenarios(sampleAllocation, 50);
    expect(scenario.after).toEqual(optimizeAllocation({ ...sampleAllocation, budget: 50 }));
    expect(scenario.after.value).toBe(52);
    expect(scenario.valueDelta).toBe(-75);
  });
  it('reports infeasibility and empty feasible allocation distinctly', () => {
    expect(optimizeAllocation({ ...sampleAllocation, budget: 0 }).status).toBe('infeasible');
    expect(optimizeAllocation({ budget: 0, items: [] })).toMatchObject({
      status: 'optimal',
      value: 0,
      selected: [],
    });
    expect(compareScenarios(sampleAllocation, 0).valueDelta).toBeNull();
  });
  it('enforces item dependencies, exclusions and deterministic tie handling', () => {
    const items = [
      { id: 'a', label: 'A', cost: 3, value: 5, category: 'x', requires: ['b'] },
      { id: 'b', label: 'B', cost: 3, value: 5, category: 'x' },
      { id: 'c', label: 'C', cost: 3, value: 5, category: 'x', excludes: ['b'] },
    ];
    expect(optimizeAllocation({ budget: 6, items }).selected.map((i) => i.id)).toEqual(['a', 'b']);
    expect(optimizeAllocation({ budget: 3, items }).selected.map((i) => i.id)).toEqual(['b']);
    expect(() =>
      optimizeAllocation({ budget: 3, items: [{ ...items[0], requires: ['unknown'] }] }),
    ).toThrow('unknown');
  });
});
