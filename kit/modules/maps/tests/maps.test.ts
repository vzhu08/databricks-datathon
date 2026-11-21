import { describe, expect, it, vi } from 'vitest';
import { filterByRadius, haversineKm, sampleLocations, sampleRoute, toGeoJSON } from '../src/index';
import { geocode, routeBetween } from '../src/server';
describe('maps', () => {
  it('calculates symmetric straight-line km including antipodes and the dateline', () => {
    expect(haversineKm([0, 0], [0, 0])).toBe(0);
    expect(haversineKm([0, 0], [180, 0])).toBeCloseTo(20015.114, 2);
    expect(haversineKm([179.9, 0], [-179.9, 0])).toBeCloseTo(22.239, 2);
    expect(haversineKm(sampleLocations[0].coordinate, sampleLocations[1].coordinate)).toBeCloseTo(
      haversineKm(sampleLocations[1].coordinate, sampleLocations[0].coordinate),
    );
    expect(() => haversineKm([200, 0], [0, 0])).toThrow();
  });
  it('filters radius and preserves empty cases and fixture provenance', () => {
    expect(
      filterByRadius(sampleLocations, sampleLocations[0].coordinate, 0).map((x) => x.id),
    ).toEqual(['library']);
    expect(filterByRadius([], [0, 0], 1)).toEqual([]);
    expect(toGeoJSON(sampleLocations, sampleRoute).features).toHaveLength(4);
    expect(sampleRoute.mode).toBe('fixture');
  });
  it('uses Mapbox v6 geocoding request and normalizes official contract shape', async () => {
    const fetcher = vi.fn(async (input: string | URL | Request) => {
      const url = new URL(String(input));
      expect(url.pathname).toBe('/search/geocode/v6/forward');
      expect(url.searchParams.get('q')).toBe('New York');
      expect(url.searchParams.get('permanent')).toBe('false');
      return Response.json({
        type: 'FeatureCollection',
        features: [
          {
            id: 'place.id',
            geometry: { type: 'Point', coordinates: [-74, 40.7] },
            properties: { name: 'New York', full_address: 'New York, NY, United States' },
          },
        ],
        attribution: '© Mapbox',
      });
    });
    const result = await geocode('New York', { token: 'test-only', fetcher });
    expect(result).toMatchObject({
      mode: 'live',
      locations: [{ name: 'New York, NY, United States', coordinate: [-74, 40.7] }],
    });
  });
  it('returns empty geocoding and rejects provider/invalid inputs', async () => {
    const empty = await geocode('Nowhere', {
      token: 'test',
      fetcher: async () => Response.json({ type: 'FeatureCollection', features: [] }),
    });
    expect(empty.locations).toEqual([]);
    await expect(geocode('x;y', { token: 'test' })).rejects.toThrow();
    await expect(
      geocode('somewhere', {
        token: 'test',
        fetcher: async () => new Response('', { status: 429 }),
      }),
    ).rejects.toThrow('429');
  });
  it('normalizes actual route distance/time, never substitutes straight-line routing', async () => {
    const fetcher = vi.fn(async (input: string | URL | Request) => {
      expect(String(input)).toContain('/directions/v5/mapbox/walking/');
      expect(String(input)).toContain('geometries=geojson');
      return Response.json({
        code: 'Ok',
        routes: [{ distance: 1200, duration: 950, geometry: sampleRoute.geometry }],
      });
    });
    expect(
      await routeBetween(sampleLocations[0].coordinate, sampleLocations[1].coordinate, 'walking', {
        token: 'test',
        fetcher,
      }),
    ).toMatchObject({ mode: 'live', distanceMeters: 1200, durationSeconds: 950 });
    await expect(
      routeBetween([0, 0], [1, 1], 'driving', {
        token: 'test',
        fetcher: async () => Response.json({ code: 'NoRoute', routes: [] }),
      }),
    ).rejects.toThrow('No traversable');
  });
});
