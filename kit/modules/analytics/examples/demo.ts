import {
  aggregate,
  cleanCsv,
  compareScenarios,
  sampleAllocation,
  sampleCsv,
  summarize,
} from '../src/index';
const cleaned = cleanCsv(sampleCsv, ['cost', 'participants']);
console.log('LOCAL calculations; SYNTHETIC event data', cleaned);
console.log('Cost summary', summarize(cleaned.rows.map((row) => row.cost as number | null)));
console.log('Daily participants', aggregate(cleaned.rows, 'day', 'participants'));
console.log('Budget what-if', compareScenarios(sampleAllocation, 50));
console.log('Infeasible budget', compareScenarios(sampleAllocation, 0).after);
