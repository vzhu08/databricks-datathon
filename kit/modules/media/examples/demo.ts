import { sampleFrameTimes, sampleVisionResult, VisionResultSchema } from '../src/index';
console.log(
  'FIXTURE authored analysis, no model request',
  VisionResultSchema.parse(sampleVisionResult),
);
console.log('Sampling plan for a synthetic 12-second video:', sampleFrameTimes(12));
console.log(
  'Empty result is valid:',
  VisionResultSchema.parse({ summary: 'No detections', detections: [], mode: 'fixture' }),
);
