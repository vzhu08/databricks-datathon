import { afterEach, describe, expect, it } from 'vitest';
import { WebSocket } from 'ws';
import { startRealtimeServer } from '../src/server';
import { RoomClient } from '../src/browser';
import { tallyVotes, type RoomState } from '../src/index';
const cleanup: (() => Promise<void> | void)[] = [];
afterEach(async () => {
  for (const close of cleanup.reverse()) await close();
  cleanup.length = 0;
});
async function until(test: () => boolean) {
  const end = Date.now() + 2000;
  while (!test()) {
    if (Date.now() > end) throw new Error('Timed out waiting for realtime state');
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}
describe('local realtime', () => {
  it('shares votes across two clients, isolates rooms, deduplicates events, reconnects and cleans presence', async () => {
    const server = await startRealtimeServer();
    cleanup.push(() => server.close());
    const make = (room: string, userId: string) => {
      const client = new RoomClient({
        url: server.url,
        room,
        userId,
        WebSocketImpl: WebSocket as unknown as typeof globalThis.WebSocket,
        reconnectMs: 5,
      });
      cleanup.push(() => client.close());
      return client;
    };
    const a = make('lunch', 'alice');
    const b = make('lunch', 'bob');
    const c = make('other', 'carol');
    let stateA: RoomState | undefined;
    let stateB: RoomState | undefined;
    let stateC: RoomState | undefined;
    a.onState((state) => {
      stateA = state;
    });
    b.onState((state) => {
      stateB = state;
    });
    c.onState((state) => {
      stateC = state;
    });
    a.connect();
    b.connect();
    c.connect();
    await until(() => stateA?.members.length === 2 && !!stateC);
    a.vote('pizza', 'event1');
    await until(() => stateB?.votes.alice === 'pizza');
    const revision = stateB!.revision;
    a.vote('sushi', 'event1');
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(stateB!.revision).toBe(revision);
    expect(stateC!.votes).toEqual({});
    for (const [socket, user] of server.rooms.get('lunch')!.sockets)
      if (user === 'alice') socket.terminate();
    await until(() => stateB!.members.length === 1);
    a.vote('sushi', 'event2');
    await until(() => stateB!.members.length === 2 && stateB!.votes.alice === 'sushi');
    expect(tallyVotes(stateB!)).toEqual([['sushi', 1]]);
    b.close();
    await until(() => stateA!.members.length === 1);
  });
  it('rejects unauthorized room joins and non-loopback insecure binds', async () => {
    await expect(startRealtimeServer({ host: '0.0.0.0' })).rejects.toThrow('authorize');
    const server = await startRealtimeServer({ authorize: async () => false });
    cleanup.push(() => server.close());
    const socket = new WebSocket(server.url);
    cleanup.push(() => socket.terminate());
    const closed = new Promise<number>((resolve) => socket.once('close', (code) => resolve(code)));
    await new Promise<void>((resolve) => socket.once('open', resolve));
    socket.send(JSON.stringify({ type: 'join', room: 'private', userId: 'alice' }));
    expect(await closed).toBe(1008);
    expect(server.rooms.size).toBe(0);
  });
  it('rejects invalid names and bounds offline event queues', () => {
    expect(() => new RoomClient({ url: 'http://localhost', room: 'a', userId: 'b' })).toThrow();
    const client = new RoomClient({ url: 'ws://localhost', room: 'a', userId: 'b' });
    for (let i = 0; i < 100; i++) client.vote('x', `id${i}`);
    expect(() => client.vote('x', 'overflow')).toThrow('queue is full');
    client.close();
    expect(tallyVotes({ room: 'a', members: [], votes: {}, revision: 0 })).toEqual([]);
  });
});
