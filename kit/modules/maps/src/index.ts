import { z } from 'zod';
export const CoordinateSchema = z.tuple([
  z.number().finite().min(-180).max(180),
  z.number().finite().min(-90).max(90),
]);
export type Coordinate = z.infer<typeof CoordinateSchema>;
const GeometrySchema = z.discriminatedUnion('type', [
  z.object({ type: z.literal('Point'), coordinates: CoordinateSchema }),
  z.object({
    type: z.literal('LineString'),
    coordinates: z.array(CoordinateSchema).min(2).max(10_000),
  }),
  z.object({
    type: z.literal('Polygon'),
    coordinates: z.array(z.array(CoordinateSchema).min(4).max(10_000)).max(100),
  }),
]);
export const FeatureSchema = z.object({
  type: z.literal('Feature'),
  id: z.union([z.string(), z.number()]).optional(),
  geometry: GeometrySchema,
  properties: z.record(z.string(), z.unknown()).nullable(),
});
export const FeatureCollectionSchema = z
  .object({ type: z.literal('FeatureCollection'), features: z.array(FeatureSchema).max(2000) })
  .superRefine((collection, context) => {
    let count = 0;
    for (const feature of collection.features) {
      const g = feature.geometry;
      if (g.type === 'Point') count++;
      else if (g.type === 'LineString') count += g.coordinates.length;
      else
        for (const ring of g.coordinates) {
          count += ring.length;
          if (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1])
            context.addIssue({ code: 'custom', message: 'GeoJSON polygon rings must be closed' });
        }
    }
    if (count > 20_000)
      context.addIssue({ code: 'custom', message: 'GeoJSON exceeds 20,000 coordinates' });
  });
export type FeatureCollection = z.infer<typeof FeatureCollectionSchema>;
export const LocationSchema = z.object({
  id: z.string(),
  name: z.string(),
  coordinate: CoordinateSchema,
});
export type Location = z.infer<typeof LocationSchema>;
export const RouteSchema = z.object({
  mode: z.enum(['fixture', 'live']),
  geometry: z.object({
    type: z.literal('LineString'),
    coordinates: z.array(CoordinateSchema).min(2).max(10_000),
  }),
  distanceMeters: z.number().nonnegative().finite(),
  durationSeconds: z.number().nonnegative().finite(),
  profile: z.enum(['walking', 'cycling', 'driving']),
  attribution: z.string(),
});
export type Route = z.infer<typeof RouteSchema>;
/** Spherical great-circle distance in km, not a travel route or travel-time estimate. */
export function haversineKm(from: Coordinate, to: Coordinate) {
  CoordinateSchema.parse(from);
  CoordinateSchema.parse(to);
  const rad = Math.PI / 180,
    lat = (to[1] - from[1]) * rad,
    lon = (to[0] - from[0]) * rad;
  const a =
    Math.sin(lat / 2) ** 2 +
    Math.cos(from[1] * rad) * Math.cos(to[1] * rad) * Math.sin(lon / 2) ** 2;
  return 6371.0088 * 2 * Math.atan2(Math.sqrt(Math.min(1, a)), Math.sqrt(Math.max(0, 1 - a)));
}
export function filterByRadius(locations: Location[], center: Coordinate, radiusKm: number) {
  z.number().finite().nonnegative().parse(radiusKm);
  return z
    .array(LocationSchema)
    .max(2000)
    .parse(locations)
    .map((l) => ({ ...l, straightLineKm: haversineKm(center, l.coordinate) }))
    .filter((l) => l.straightLineKm <= radiusKm)
    .sort((a, b) => a.straightLineKm - b.straightLineKm || a.id.localeCompare(b.id));
}
export function toGeoJSON(locations: Location[], route?: Route): FeatureCollection {
  const features: FeatureCollection['features'] = locations.map((l) => ({
    type: 'Feature',
    id: l.id,
    geometry: { type: 'Point', coordinates: l.coordinate },
    properties: { name: l.name },
  }));
  if (route)
    features.unshift({
      type: 'Feature',
      id: 'route',
      geometry: route.geometry,
      properties: { name: `${route.mode} ${route.profile} route` },
    });
  return FeatureCollectionSchema.parse({ type: 'FeatureCollection', features });
}
export const sampleLocations: Location[] = [
  { id: 'library', name: 'Sample library', coordinate: [-73.9855, 40.7535] },
  { id: 'garden', name: 'Sample garden', coordinate: [-73.983, 40.757] },
  { id: 'hall', name: 'Sample event hall', coordinate: [-73.9805, 40.7525] },
];
export const sampleRoute: Route = {
  mode: 'fixture',
  geometry: {
    type: 'LineString',
    coordinates: [
      sampleLocations[0].coordinate,
      [-73.9827, 40.7545],
      sampleLocations[1].coordinate,
    ],
  },
  distanceMeters: 640,
  durationSeconds: 500,
  profile: 'walking',
  attribution: 'Synthetic schematic route; not navigation guidance or fetched map data',
};
