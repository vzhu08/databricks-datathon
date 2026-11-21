import { startRealtimeServer } from '../src/server';
const server = await startRealtimeServer({ port: Number(process.env.REALTIME_PORT ?? 8788) });
console.log(`Local ephemeral realtime: ${server.url}`);
for (const signal of ['SIGINT', 'SIGTERM'] as const)
  process.once(signal, () => {
    void server.close();
  });
