import Papa from 'papaparse';
import { z } from 'zod';

export type CleanRow = Record<string, string | number | null>;
export function cleanCsv(csv: string, numericColumns: string[] = [], maxRows = 10_000) {
  if (new TextEncoder().encode(csv).length > 2_000_000) throw new Error('CSV exceeds 2 MB limit');
  z.number().int().min(1).max(100_000).parse(maxRows);
  const result = Papa.parse<string[]>(csv, { delimiter: ',', skipEmptyLines: 'greedy' });
  if (result.errors.length) throw new Error(`CSV parse error: ${result.errors[0].message}`);
  if (!result.data.length)
    return {
      rows: [] as CleanRow[],
      columns: [] as string[],
      issues: [] as string[],
      mode: 'local' as const,
    };
  const columns = result.data[0].map((v, i) => (i === 0 ? v.replace(/^\uFEFF/, '') : v).trim());
  if (columns.length > 200) throw new Error('CSV exceeds 200 columns');
  if (columns.some((c) => !c) || new Set(columns).size !== columns.length)
    throw new Error('CSV headers must be unique and nonempty');
  if (numericColumns.some((c) => !columns.includes(c)))
    throw new Error('Numeric column does not exist');
  if (result.data.length - 1 > maxRows) throw new Error(`CSV exceeds ${maxRows} rows`);
  const issues: string[] = [];
  const rows = result.data.slice(1).map((fields, i) => {
    if (fields.length !== columns.length)
      issues.push(`Row ${i + 2}: expected ${columns.length} fields, got ${fields.length}`);
    return Object.fromEntries(
      columns.map((column, j) => {
        const raw = (fields[j] ?? '').trim();
        if (!raw || /^(null|n\/a|na)$/i.test(raw)) return [column, null];
        if (!numericColumns.includes(column)) return [column, raw];
        const value = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(raw) ? Number(raw) : NaN;
        if (!Number.isFinite(value)) {
          issues.push(`Row ${i + 2}, ${column}: invalid number treated as missing`);
          return [column, null];
        }
        return [column, value];
      }),
    ) as CleanRow;
  });
  return { rows, columns, issues, mode: 'local' as const };
}
export function summarize(values: (number | null | undefined)[]) {
  const valid = values
    .filter((v): v is number => typeof v === 'number' && Number.isFinite(v))
    .sort((a, b) => a - b);
  const n = valid.length,
    mean = n ? valid.reduce((a, b) => a + b, 0) / n : null;
  return {
    count: n,
    missing: values.length - n,
    sum: valid.reduce((a, b) => a + b, 0),
    mean,
    median: n ? (valid[Math.floor((n - 1) / 2)] + valid[Math.floor(n / 2)]) / 2 : null,
    min: n ? valid[0] : null,
    max: n ? valid[n - 1] : null,
    standardDeviation:
      mean !== null ? Math.sqrt(valid.reduce((s, v) => s + (v - mean) ** 2, 0) / n) : null,
  };
}
export type ChartDatum = { label: string; value: number };
export function aggregate(rows: CleanRow[], category: string, metric: string): ChartDatum[] {
  const groups = new Map<string, number>();
  for (const row of rows) {
    const value = row[metric];
    if (typeof value !== 'number' || !Number.isFinite(value)) continue;
    const label = String(row[category] ?? '(missing)');
    groups.set(label, (groups.get(label) ?? 0) + value);
  }
  return [...groups]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([label, value]) => ({ label, value }));
}
export function scoreRow(
  row: CleanRow,
  rules: {
    column: string;
    weight: number;
    min: number;
    max: number;
    direction: 'higher' | 'lower';
  }[],
) {
  const parsed = z
    .array(
      z
        .object({
          column: z.string(),
          weight: z.number().nonnegative(),
          min: z.number().finite(),
          max: z.number().finite(),
          direction: z.enum(['higher', 'lower']),
        })
        .refine((r) => r.max > r.min),
    )
    .parse(rules);
  const weight = parsed.reduce((s, r) => s + r.weight, 0);
  const contributions = parsed.map((r) => {
    const value = row[r.column];
    const normalized =
      typeof value === 'number' && Number.isFinite(value)
        ? Math.max(0, Math.min(1, (value - r.min) / (r.max - r.min)))
        : null;
    return {
      column: r.column,
      value: value ?? null,
      contribution:
        normalized === null || !weight
          ? 0
          : ((r.direction === 'higher' ? normalized : 1 - normalized) * r.weight) / weight,
    };
  });
  return { score: contributions.reduce((s, c) => s + c.contribution, 0), contributions };
}
export const AllocationSchema = z
  .object({
    budget: z.number().int().min(0).max(1_000_000),
    minItems: z.number().int().min(0).max(20).default(0),
    maxItems: z.number().int().min(0).max(20).default(20),
    requiredCategories: z.array(z.string()).max(20).default([]),
    items: z
      .array(
        z.object({
          id: z.string().min(1),
          label: z.string(),
          cost: z.number().int().min(0).max(1_000_000),
          value: z.number().finite().min(0).max(1_000_000),
          category: z.string(),
          requires: z.array(z.string()).default([]),
          excludes: z.array(z.string()).default([]),
        }),
      )
      .max(20),
  })
  .refine((p) => p.minItems <= p.maxItems, 'Minimum exceeds maximum item count');
export type AllocationProblem = z.infer<typeof AllocationSchema>;
/** Exact bounded binary allocation: maximize value, then minimize cost, then stable ID order. */
export function optimizeAllocation(input: unknown) {
  const p = AllocationSchema.parse(input);
  const ids = new Set(p.items.map((i) => i.id));
  if (
    ids.size !== p.items.length ||
    p.items.some((i) => [...i.requires, ...i.excludes].some((id) => !ids.has(id)))
  )
    throw new Error('Duplicate or unknown allocation item reference');
  const items = [...p.items].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  let best: { selected: typeof items; cost: number; value: number; key: string } | null = null;
  let evaluated = 0;
  function search(at: number, selected: typeof items, cost: number, value: number) {
    if (
      cost > p.budget ||
      selected.length > p.maxItems ||
      selected.length + items.length - at < p.minItems
    )
      return;
    if (at < items.length) {
      search(at + 1, selected, cost, value);
      search(at + 1, [...selected, items[at]], cost + items[at].cost, value + items[at].value);
      return;
    }
    evaluated++;
    if (selected.length < p.minItems) return;
    const chosen = new Set(selected.map((i) => i.id));
    if (
      p.requiredCategories.some((c) => !selected.some((i) => i.category === c)) ||
      selected.some(
        (i) => i.requires.some((id) => !chosen.has(id)) || i.excludes.some((id) => chosen.has(id)),
      )
    )
      return;
    const key = selected.map((i) => i.id).join('\u0000');
    if (
      !best ||
      value > best.value ||
      (value === best.value && (cost < best.cost || (cost === best.cost && key < best.key)))
    )
      best = { selected, cost, value, key };
  }
  search(0, [], 0, 0);
  const solution = best as {
    selected: typeof items;
    cost: number;
    value: number;
    key: string;
  } | null;
  return solution
    ? {
        status: 'optimal' as const,
        selected: solution.selected,
        cost: solution.cost,
        value: solution.value,
        remaining: p.budget - solution.cost,
        evaluated,
        mode: 'local' as const,
      }
    : {
        status: 'infeasible' as const,
        reason:
          'No selection satisfies the budget, cardinality, category, dependency and exclusion constraints.',
        selected: [],
        cost: 0,
        value: 0,
        remaining: p.budget,
        evaluated,
        mode: 'local' as const,
      };
}
export function compareScenarios(problem: unknown, nextBudget: number) {
  const parsed = AllocationSchema.parse(problem),
    before = optimizeAllocation(parsed),
    after = optimizeAllocation({ ...parsed, budget: nextBudget });
  return {
    before,
    after,
    valueDelta:
      before.status === 'optimal' && after.status === 'optimal' ? after.value - before.value : null,
  };
}
export const sampleAllocation: AllocationProblem = AllocationSchema.parse({
  budget: 100,
  minItems: 2,
  maxItems: 3,
  requiredCategories: ['access'],
  items: [
    { id: 'captions', label: 'Live captions', cost: 30, value: 40, category: 'access' },
    { id: 'food', label: 'Snack table', cost: 45, value: 50, category: 'comfort' },
    { id: 'mentors', label: 'Mentor hours', cost: 60, value: 75, category: 'learning' },
    { id: 'signage', label: 'Clear signs', cost: 10, value: 12, category: 'access' },
  ],
});
export const sampleCsv =
  'day,category,cost,participants\n2026-01-01,workshop,25,12\n2026-01-01,mentoring,30,8\n2026-01-02,workshop,,16\n2026-01-02,mentoring,invalid,10\n';
