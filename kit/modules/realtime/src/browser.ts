import { RoomStateSchema, IdentifierSchema, type RoomState } from './index';
export class RoomClient {
  private socket?: WebSocket;
  private timer?: ReturnType<typeof setTimeout>;
  private stopped = true;
  private retries = 0;
  private pending = new Map<string, string>();
  private listeners = new Set<(state: RoomState) => void>();
  private latest?: RoomState;
  private joined = false;
  constructor(
    private options: {
      url: string;
      room: string;
      userId: string;
      token?: string;
      WebSocketImpl?: typeof WebSocket;
      maxReconnects?: number;
      reconnectMs?: number;
      onStatus?: (
        status: 'connecting' | 'connected' | 'disconnected' | 'error',
        message?: string,
      ) => void;
    },
  ) {
    IdentifierSchema.parse(options.room);
    IdentifierSchema.parse(options.userId);
    const url = new URL(options.url);
    if (!['ws:', 'wss:'].includes(url.protocol)) throw new Error('Expected ws or wss URL');
  }
  connect() {
    if (!this.stopped) return;
    this.stopped = false;
    this.open();
  }
  private open() {
    if (this.stopped) return;
    this.joined = false;
    this.options.onStatus?.('connecting');
    const Socket = this.options.WebSocketImpl ?? WebSocket;
    const socket = new Socket(this.options.url);
    this.socket = socket;
    socket.onopen = () =>
      socket.send(
        JSON.stringify({
          type: 'join',
          room: this.options.room,
          userId: this.options.userId,
          token: this.options.token,
        }),
      );
    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(String(event.data));
        if (message.type === 'state') {
          const state = RoomStateSchema.parse(message.state);
          if (state.room !== this.options.room) throw new Error('Wrong room received');
          const needsReplay = !this.joined;
          this.latest = state;
          this.joined = true;
          this.retries = 0;
          this.options.onStatus?.('connected');
          for (const listener of this.listeners) listener(structuredClone(state));
          if (needsReplay)
            for (const [id, choice] of this.pending)
              socket.send(JSON.stringify({ type: 'vote', id, choice }));
        } else if (message.type === 'ack') this.pending.delete(String(message.id));
        else if (message.type === 'error')
          this.options.onStatus?.('error', String(message.message));
      } catch (error) {
        this.options.onStatus?.('error', error instanceof Error ? error.message : 'Invalid state');
      }
    };
    socket.onerror = () => this.options.onStatus?.('error', 'Connection failed');
    socket.onclose = (event) => {
      if (this.stopped) return;
      this.options.onStatus?.('disconnected');
      if (event.code === 1008 || this.retries >= (this.options.maxReconnects ?? 8)) return;
      const wait = Math.min(10_000, (this.options.reconnectMs ?? 100) * 2 ** this.retries++);
      this.timer = setTimeout(() => this.open(), wait);
    };
  }
  vote(choice: string, eventId: string = crypto.randomUUID()) {
    if (!choice || choice.length > 120) throw new Error('Choice must contain 1–120 characters');
    IdentifierSchema.parse(eventId);
    if (this.pending.size >= 100 && !this.pending.has(eventId))
      throw new Error('Offline event queue is full');
    this.pending.set(eventId, choice);
    if (this.socket?.readyState === 1 && this.joined)
      this.socket.send(JSON.stringify({ type: 'vote', id: eventId, choice }));
    return eventId;
  }
  onState(listener: (state: RoomState) => void) {
    this.listeners.add(listener);
    if (this.latest) listener(structuredClone(this.latest));
    return () => {
      this.listeners.delete(listener);
    };
  }
  close() {
    this.stopped = true;
    clearTimeout(this.timer);
    this.socket?.close();
    this.socket = undefined;
    this.pending.clear();
    this.latest = undefined;
    this.listeners.clear();
  }
}
