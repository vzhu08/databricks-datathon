import { WebSocketServer, WebSocket } from 'ws';
import { ClientMessageSchema, type RoomState } from './index';
type Room = { state: RoomState; sockets: Map<WebSocket, string>; seen: Set<string> };
export async function startRealtimeServer(
  options: {
    port?: number;
    host?: string;
    maxRooms?: number;
    maxClients?: number;
    maxVotesPerRoom?: number;
    authorize?: (identity: { room: string; userId: string; token?: string }) => Promise<boolean>;
  } = {},
) {
  const host = options.host ?? '127.0.0.1';
  if (!['127.0.0.1', 'localhost', '::1'].includes(host) && !options.authorize)
    throw new Error('Non-loopback realtime requires an authorize callback');
  const rooms = new Map<string, Room>();
  const server = new WebSocketServer({ host, port: options.port ?? 0, maxPayload: 8192 });
  const send = (socket: WebSocket, message: unknown) => {
    if (socket.bufferedAmount > 1_000_000) {
      socket.close(1013, 'Slow client');
      return;
    }
    if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
  };
  const broadcast = (room: Room) => {
    room.state.members = [...new Set(room.sockets.values())].sort();
    room.state.revision++;
    for (const socket of room.sockets.keys()) send(socket, { type: 'state', state: room.state });
  };
  server.on('connection', (socket) => {
    if (server.clients.size > (options.maxClients ?? 100)) {
      socket.close(1013, 'Client capacity reached');
      return;
    }
    let room: Room | undefined;
    let userId = '';
    let joining = false;
    let windowStart = Date.now();
    let messages = 0;
    const joinDeadline = setTimeout(() => {
      if (!room) socket.close(1008, 'Join required');
    }, 5000);
    joinDeadline.unref();
    socket.on('message', async (raw) => {
      try {
        if (Date.now() - windowStart > 60_000) {
          windowStart = Date.now();
          messages = 0;
        }
        if (++messages > 200) throw new Error('Rate limit exceeded');
        const message = ClientMessageSchema.parse(JSON.parse(raw.toString()));
        if (message.type === 'join') {
          if (room || joining) throw new Error('Already joined');
          joining = true;
          if (options.authorize && !(await options.authorize(message)))
            throw new Error('Unauthorized room');
          if (socket.readyState !== WebSocket.OPEN) return;
          room = rooms.get(message.room);
          if (!room) {
            if (rooms.size >= (options.maxRooms ?? 100)) throw new Error('Room capacity reached');
            room = {
              state: { room: message.room, members: [], votes: {}, revision: 0 },
              sockets: new Map(),
              seen: new Set(),
            };
            rooms.set(message.room, room);
          }
          userId = message.userId;
          room.sockets.set(socket, userId);
          clearTimeout(joinDeadline);
          broadcast(room);
        } else {
          if (!room) throw new Error('Join a room first');
          const key = `${userId}:${message.id}`;
          if (!room.seen.has(key)) {
            if (
              !(userId in room.state.votes) &&
              Object.keys(room.state.votes).length >= (options.maxVotesPerRoom ?? 1000)
            )
              throw new Error('Room vote capacity reached');
            room.seen.add(key);
            while (room.seen.size > 2000) room.seen.delete(room.seen.values().next().value!);
            room.state.votes[userId] = message.choice;
            broadcast(room);
          }
          send(socket, { type: 'ack', id: message.id });
        }
      } catch (error) {
        send(socket, {
          type: 'error',
          message: error instanceof Error ? error.message : 'Invalid message',
        });
        socket.close(1008, 'Invalid or unauthorized message');
      }
    });
    socket.on('close', () => {
      clearTimeout(joinDeadline);
      if (room) {
        room.sockets.delete(socket);
        broadcast(room);
      }
    });
    socket.on('error', () => {});
  });
  await new Promise<void>((resolve, reject) => {
    server.once('listening', resolve);
    server.once('error', reject);
  });
  const address = server.address();
  if (typeof address === 'string' || !address) throw new Error('No server address');
  return {
    url: `ws://${host.includes(':') ? `[${host}]` : host}:${address.port}`,
    rooms,
    async close() {
      for (const socket of server.clients) socket.terminate();
      await new Promise<void>((resolve, reject) =>
        server.close((error) => (error ? reject(error) : resolve())),
      );
    },
  };
}
