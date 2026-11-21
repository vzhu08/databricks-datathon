import { parseArgs } from 'node:util';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { performance } from 'node:perf_hooks';
import { transformText } from '../packages/runtime/src/index';
import { normalizeText } from '../modules/documents/src/index';
import { LocalIndex, evaluateRetrieval } from '../modules/retrieval/src/index';
import {
  rankCandidates,
  sampleCandidates,
  samplePreferences,
} from '../modules/recommendations/src/index';
import { sampleText } from '../examples/document-workbench/sample';
import { configuredLiveAI } from './live-policy';
const { values } = parseArgs({
  options: {
    output: { type: 'string' },
    'max-cases': { type: 'string' },
    live: { type: 'boolean' },
    'confirm-usage': { type: 'boolean' },
  },
});
const maximum = Number(values['max-cases'] ?? 10);
if (!Number.isInteger(maximum) || maximum < 1 || maximum > 10)
  throw new Error('max-cases must be 1–10 total cases');
const results: {
  id: string;
  passed: boolean;
  latencyMs: number;
  output?: string;
  error?: string;
  usage?: unknown;
}[] = [];
let configuration: unknown = {
    mode: 'local',
    provider: null,
    model: null,
    concurrency: 1,
    maxCases: maximum,
  },
  retrieval: unknown = null,
  estimatedCostUSD: number | null = 0;
if (values.live) {
  const ai = configuredLiveAI({
    enabled: true,
    confirmed: !!values['confirm-usage'],
    maxCalls: maximum,
  });
  configuration = { mode: 'live', dataset: 'label-exact-v1', promptVersion: '1.0.0', ...ai.policy };
  estimatedCostUSD = null;
  const cases = [
    { input: 'apple', expected: 'fruit' },
    { input: 'car', expected: 'vehicle' },
    { input: 'pear', expected: 'fruit' },
    { input: 'bicycle', expected: 'vehicle' },
    { input: 'cloud', expected: 'other' },
  ].slice(0, maximum);
  for (const item of cases) {
    const start = performance.now();
    try {
      const answer = await ai.generate(
        `Classify the word between <input> tags as fruit, vehicle, or other. Reply with exactly one of those lowercase labels, no punctuation. <input>${item.input}</input>`,
      );
      results.push({
        id: item.input,
        passed: answer.text.trim() === item.expected,
        latencyMs: answer.latencyMs,
        output: answer.text,
        usage: answer.usage,
      });
    } catch {
      results.push({
        id: item.input,
        passed: false,
        latencyMs: performance.now() - start,
        error: 'Provider or schema failure; inspect configured adapter with sanitized logs.',
      });
    }
  }
} else {
  const index = new LocalIndex();
  const doc = normalizeText({ filename: 'garden.txt', text: sampleText });
  index.upsert(doc);
  const cases = [
    { id: 'normalization', run: () => transformText({ text: ' a   b ' }).text === 'a b' },
    { id: 'empty-transform', run: () => transformText({ text: '' }).words === 0 },
    {
      id: 'invalid-transform',
      run: () => {
        try {
          transformText({ text: 12 });
          return false;
        } catch {
          return true;
        }
      },
    },
    {
      id: 'group-hard-constraints',
      run: () =>
        rankCandidates(sampleCandidates, samplePreferences).excluded.some(
          (e) => e.id === 'rooftop',
        ),
    },
    { id: 'empty-pool', run: () => rankCandidates([], samplePreferences).ranked.length === 0 },
    ...['budget', 'wheelchair paths', 'deadline'].map((query) => ({
      id: `retrieve-${query.replaceAll(' ', '-')}`,
      run: () => {
        const metric = evaluateRetrieval(index, [{ query, expectedDocumentId: doc.id }], 3);
        return metric.recallAtK === 1 && metric.citationValidity === 1;
      },
    })),
  ].slice(0, maximum);
  for (const c of cases) {
    const start = performance.now();
    let passed = false,
      error: string | undefined;
    try {
      passed = c.run();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
    results.push({
      id: c.id,
      passed,
      latencyMs: performance.now() - start,
      ...(error ? { error } : {}),
    });
  }
  const retrievalCases = cases.filter((c) => c.id.startsWith('retrieve-'));
  retrieval = {
    cases: retrievalCases.length,
    allReturnedCitationsChecked: true,
    description:
      'Recall@3 and exact source citation validity checked in each selected retrieval case; no extra uncounted calls.',
  };
}
const report = {
  schemaVersion: 1,
  dataset: values.live ? 'synthetic-label-exact-v1' : 'synthetic-kit-v1',
  createdAt: new Date().toISOString(),
  configuration,
  results,
  metrics: { passRate: results.filter((r) => r.passed).length / results.length, retrieval },
  estimatedCostUSD,
  costBasis: values.live
    ? 'Unknown: no dated provider price table configured. Recorded token usage per case.'
    : 'No external requests; local deterministic operations',
  limitations: [
    'Small authored sanity dataset; not a claim of general retrieval/model quality.',
    'Exact-label correctness; no LLM-as-judge scoring.',
    'Wall-clock values vary with host load.',
  ],
};
const dir = path.resolve(values.output ?? `.kit/evaluations/${values.live ? 'live' : 'local'}`);
await mkdir(dir, { recursive: true });
await writeFile(path.join(dir, 'results.json'), JSON.stringify(report, null, 2) + '\n');
await writeFile(
  path.join(dir, 'REPORT.md'),
  `# ${values.live ? 'Live provider' : 'Local deterministic'} evaluation\n\nDataset ${report.dataset}; ${results.length} cases, ${(report.metrics.passRate * 100).toFixed(0)}% passed. Cost: ${estimatedCostUSD === null ? 'unknown' : estimatedCostUSD + ' USD'}. ${report.costBasis}\n\n| Case | Passed | Latency ms |\n|---|---|---|\n${results.map((r) => `| ${r.id} | ${r.passed} | ${r.latencyMs.toFixed(2)} |`).join('\n')}\n\n${report.limitations.join(' ')}\n`,
);
console.log(JSON.stringify(report, null, 2));
if (results.some((r) => !r.passed)) process.exitCode = 1;
