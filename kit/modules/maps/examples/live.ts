import { geocode, routeBetween } from '../src/server';
if (process.env.KIT_ALLOW_LIVE !== '1')
  throw new Error(
    'Live requests may incur usage; explicitly set KIT_ALLOW_LIVE=1 after configuring a test account.',
  );
const token = process.env.MAPBOX_ACCESS_TOKEN;
if (!token) throw new Error('Set MAPBOX_ACCESS_TOKEN on the server');
const result = await geocode(process.argv[2] ?? 'New York Public Library', { token });
console.log(result);
if (result.locations.length >= 2)
  console.log(
    await routeBetween(result.locations[0].coordinate, result.locations[1].coordinate, 'walking', {
      token,
    }),
  );
