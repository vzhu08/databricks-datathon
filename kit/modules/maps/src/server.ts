import { z } from 'zod';
import { httpJson, KitError } from '../../../packages/runtime/src/index';
import { CoordinateSchema, RouteSchema, type Coordinate, type Location } from './index';
export type MapboxOptions = { token: string; fetcher?: typeof fetch; signal?: AbortSignal };
function token(options: MapboxOptions) {
  return z.string().min(1, 'Mapbox access token required').parse(options.token);
}
export async function geocode(query: string, options: MapboxOptions) {
  const q = z
    .string()
    .trim()
    .min(1)
    .max(256)
    .refine(
      (v) => !v.includes(';') && v.split(/\s+/).length <= 20,
      'Use at most 20 words and no semicolons',
    )
    .parse(query);
  const url = new URL('https://api.mapbox.com/search/geocode/v6/forward');
  url.search = new URLSearchParams({
    q,
    access_token: token(options),
    limit: '5',
    autocomplete: 'false',
    permanent: 'false',
  }).toString();
  const response = await httpJson(
    url,
    z.object({
      type: z.literal('FeatureCollection'),
      features: z
        .array(
          z.object({
            id: z.string(),
            geometry: z.object({ type: z.literal('Point'), coordinates: CoordinateSchema }),
            properties: z.object({ full_address: z.string().optional(), name: z.string() }),
          }),
        )
        .max(10),
      attribution: z.string().optional(),
    }),
    {
      fetcher: options.fetcher,
      signal: options.signal,
      timeoutMs: 15_000,
      maxResponseBytes: 200_000,
    },
  );
  const locations: Location[] = response.features.map((f) => ({
    id: f.id,
    name: f.properties.full_address ?? f.properties.name,
    coordinate: f.geometry.coordinates,
  }));
  return {
    mode: 'live' as const,
    locations,
    attribution: response.attribution ?? '© Mapbox',
    storage: 'temporary; do not cache or persist',
  };
}
export async function routeBetween(
  from: Coordinate,
  to: Coordinate,
  profile: 'walking' | 'cycling' | 'driving',
  options: MapboxOptions,
) {
  CoordinateSchema.parse(from);
  CoordinateSchema.parse(to);
  z.enum(['walking', 'cycling', 'driving']).parse(profile);
  const url = new URL(
    `https://api.mapbox.com/directions/v5/mapbox/${profile}/${from.join(',')};${to.join(',')}`,
  );
  url.search = new URLSearchParams({
    access_token: token(options),
    geometries: 'geojson',
    overview: 'full',
    alternatives: 'false',
    steps: 'false',
  }).toString();
  const response = await httpJson(
    url,
    z.object({
      code: z.string(),
      routes: z
        .array(
          z.object({
            distance: z.number().nonnegative(),
            duration: z.number().nonnegative(),
            geometry: RouteSchema.shape.geometry,
          }),
        )
        .optional(),
    }),
    { fetcher: options.fetcher, signal: options.signal, maxResponseBytes: 1_000_000 },
  );
  if (response.code === 'NoRoute')
    throw new KitError('NO_ROUTE', 'No traversable route between those locations', 422);
  if (response.code !== 'Ok' || !response.routes?.[0])
    throw new KitError('INVALID_ROUTE', 'Directions provider returned no valid route', 502);
  const route = response.routes[0];
  return RouteSchema.parse({
    mode: 'live',
    geometry: route.geometry,
    distanceMeters: route.distance,
    durationSeconds: route.duration,
    profile,
    attribution: '© Mapbox © OpenStreetMap',
  });
}
