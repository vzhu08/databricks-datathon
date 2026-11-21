'use client';
import { useMemo, useState } from 'react';
import { FeatureCollectionSchema, type Coordinate, type FeatureCollection } from './index';
/** Dependency-free schematic GeoJSON map. Does not request tiles or represent navigational accuracy. */
export function GeoMap({
  data,
  mode = 'fixture',
  attribution = 'Local schematic · no basemap requested',
}: {
  data: FeatureCollection;
  mode?: 'fixture' | 'live' | 'local';
  attribution?: string;
}) {
  const [zoom, setZoom] = useState(1);
  const parsed = useMemo(() => FeatureCollectionSchema.safeParse(data), [data]);
  if (!parsed.success)
    return (
      <p role="alert">Invalid GeoJSON: supported geometries are Point, LineString and Polygon.</p>
    );
  const features = parsed.data.features;
  if (!features.length) return <p>No locations to display.</p>;
  const all: Coordinate[] = features.flatMap((f) =>
    f.geometry.type === 'Point'
      ? [f.geometry.coordinates]
      : f.geometry.type === 'LineString'
        ? f.geometry.coordinates
        : f.geometry.coordinates.flat(),
  );
  if (!all.length) return <p>No coordinates to display.</p>;
  const minLon = Math.min(...all.map((p) => p[0])),
    maxLon = Math.max(...all.map((p) => p[0])),
    minLat = Math.min(...all.map((p) => p[1])),
    maxLat = Math.max(...all.map((p) => p[1]));
  const spanLon = Math.max(maxLon - minLon, 0.001),
    spanLat = Math.max(maxLat - minLat, 0.001),
    midLon = (minLon + maxLon) / 2,
    midLat = (minLat + maxLat) / 2;
  const point = ([lon, lat]: Coordinate) => [
    300 + ((lon - midLon) / spanLon) * 480 * zoom,
    180 - ((lat - midLat) / spanLat) * 240 * zoom,
  ];
  return (
    <figure>
      <figcaption>{mode} · GeoJSON schematic map</figcaption>
      <div>
        <button
          type="button"
          aria-label="Zoom out map"
          onClick={() => setZoom((v) => Math.max(0.5, v - 0.25))}
        >
          −
        </button>
        <button type="button" aria-label="Reset map zoom" onClick={() => setZoom(1)}>
          Reset
        </button>
        <button
          type="button"
          aria-label="Zoom in map"
          onClick={() => setZoom((v) => Math.min(3, v + 0.25))}
        >
          +
        </button>
      </div>
      <svg
        viewBox="0 0 600 360"
        role="img"
        aria-label="Locations and route schematic"
        style={{ width: '100%', background: '#edf5f1', borderRadius: 12 }}
      >
        <path
          d="M0 90H600 M0 180H600 M0 270H600 M150 0V360 M300 0V360 M450 0V360"
          fill="none"
          stroke="#d6e4dd"
        />
        {features.map((f, i) => {
          const name = String(f.properties?.name ?? f.id ?? `Feature ${i + 1}`);
          const g = f.geometry;
          if (g.type === 'Point') {
            const [x, y] = point(g.coordinates);
            return (
              <g key={i}>
                <circle cx={x} cy={y} r="7" fill="#166d62">
                  <title>
                    {name}: {g.coordinates.join(', ')}
                  </title>
                </circle>
                <text x={x + 12} y={y - 8} fontSize="12" fill="#173d35">
                  {name}
                </text>
              </g>
            );
          }
          if (g.type === 'LineString')
            return (
              <polyline
                key={i}
                points={g.coordinates.map((p) => point(p).join(',')).join(' ')}
                stroke="#167a9b"
                strokeWidth="4"
                fill="none"
              >
                <title>{name}</title>
              </polyline>
            );
          return (
            <path
              key={i}
              d={g.coordinates
                .map((ring) => `M${ring.map((p) => point(p).join(',')).join(' L')}Z`)
                .join(' ')}
              fill="#74b5a855"
              fillRule="evenodd"
              stroke="#398c79"
            >
              <title>{name}</title>
            </path>
          );
        })}
      </svg>
      <small>
        {attribution}. Projection is schematic; straight-line distance is not travel distance.
      </small>
    </figure>
  );
}
