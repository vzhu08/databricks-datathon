import { filterByRadius, sampleLocations, sampleRoute, toGeoJSON } from '../src/index';
console.log('FIXTURE locations/route; no tiles, geocoding or navigation fetched');
console.log(
  'Within 0.5 km straight-line',
  filterByRadius(sampleLocations, sampleLocations[0].coordinate, 0.5),
);
console.log(JSON.stringify(toGeoJSON(sampleLocations, sampleRoute), null, 2));
