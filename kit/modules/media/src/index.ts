import { z } from 'zod';
export const BoxSchema = z
  .object({
    x: z.number().finite().min(0).max(1),
    y: z.number().finite().min(0).max(1),
    width: z.number().finite().min(0).max(1),
    height: z.number().finite().min(0).max(1),
  })
  .refine(
    (b) => b.x + b.width <= 1.000001 && b.y + b.height <= 1.000001,
    'Bounding box must fit inside image',
  );
export const VisionResultSchema = z.object({
  summary: z.string().max(5000),
  detections: z
    .array(
      z.object({
        label: z.string().min(1).max(200),
        confidence: z.number().finite().min(0).max(1),
        box: BoxSchema,
      }),
    )
    .max(50),
  mode: z.enum(['fixture', 'live']),
  model: z.string().optional(),
});
export type VisionResult = z.infer<typeof VisionResultSchema>;
export type PreparedImage = {
  blob: Blob;
  width: number;
  height: number;
  mimeType: 'image/jpeg';
  originalBytes: number;
};
export type VideoFrame = { timestampSeconds: number; image: PreparedImage };
export const sampleVisionResult: VisionResult = {
  summary:
    'Synthetic colored-shape fixture. Boxes are authored fixture coordinates, not model output.',
  mode: 'fixture',
  detections: [
    { label: 'orange rectangle', confidence: 1, box: { x: 0.1, y: 0.2, width: 0.4, height: 0.6 } },
    { label: 'blue square', confidence: 1, box: { x: 0.65, y: 0.25, width: 0.25, height: 0.5 } },
  ],
};
export const sampleImageSvg =
  '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200" viewBox="0 0 400 200"><rect width="400" height="200" fill="#f4f1e9"/><rect x="40" y="40" width="160" height="120" fill="#e48b44"/><rect x="260" y="50" width="100" height="100" fill="#3e83ba"/></svg>';
export function sampleFrameTimes(durationSeconds: number, count = 6, maxDurationSeconds = 120) {
  z.number().finite().positive().max(maxDurationSeconds).parse(durationSeconds);
  z.number().int().min(1).max(12).parse(count);
  z.number().finite().positive().max(600).parse(maxDurationSeconds);
  const last = Math.max(0, durationSeconds - Math.min(0.05, durationSeconds / 2));
  return Array.from({ length: count }, (_, i) => (count === 1 ? 0 : (last * i) / (count - 1)));
}
