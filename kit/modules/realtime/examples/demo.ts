import { WebSocket } from 'ws';
import { startRealtimeServer } from '../src/server';
import { RoomClient } from '../src/browser';
const server = await startRealtimeServer();
const alice = new RoomClient({
  url: server.url,
  room: 'demo',
  userId: 'alice',
  WebSocketImpl: WebSocket as unknown as typeof globalThis.WebSocket,
});
const bob = new RoomClient({
  url: server.url,
  room: 'demo',
  userId: 'bob',
  WebSocketImpl: WebSocket as unknown as typeof globalThis.WebSocket,
});
try {
  await new Promise<void>((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('Two-client demo timeout')), 3000);
    bob.onState((state) => {
      console.log({ mode: 'local', ...state });
      if (state.votes.alice === 'pizza') {
        clearTimeout(timeout);
        resolve();
      }
    });
    alice.connect();
    bob.connect();
    alice.vote('pizza');
  });
} finally {
  alice.close();
  bob.close();
  await server.close();
}
