import { z } from 'zod';
export const EmailSchema = z.object({
  from: z.email(),
  to: z.array(z.email()).min(1).max(10),
  subject: z.string().min(1).max(200),
  text: z.string().min(1).max(100_000),
});
export const NotificationSchema = z.object({
  channel: z.string().min(1).max(100),
  text: z.string().min(1).max(4000),
});
const zonedDate = z.iso.datetime({ offset: true });
export const CalendarEventInputSchema = z
  .object({
    summary: z.string().min(1).max(200),
    start: zonedDate,
    end: zonedDate,
    timeZone: z.string().refine((value) => {
      try {
        new Intl.DateTimeFormat('en', { timeZone: value });
        return true;
      } catch {
        return false;
      }
    }, 'Expected IANA time zone'),
    description: z.string().max(10_000).optional(),
  })
  .refine((value) => Date.parse(value.end) > Date.parse(value.start), 'End must follow start');
export type Email = z.infer<typeof EmailSchema>;
export type Notification = z.infer<typeof NotificationSchema>;
export type CalendarEventInput = z.infer<typeof CalendarEventInputSchema>;
export type CalendarEvent = CalendarEventInput & { id: string; mode: 'fixture' | 'live' };
export type SendIntent = { authorized: true; idempotencyKey: string };
export const SendIntentSchema = z.object({
  authorized: z.literal(true),
  idempotencyKey: z.string().min(1).max(200),
});
export interface EmailAdapter {
  send(message: Email, intent: SendIntent): Promise<{ id: string; mode: 'local' | 'live' }>;
}
export interface MessagingAdapter {
  post(message: Notification, intent: SendIntent): Promise<{ id: string; mode: 'local' | 'live' }>;
}
export interface CalendarAdapter {
  list(from: string, to: string): Promise<CalendarEvent[]>;
  create(input: CalendarEventInput, intent: SendIntent): Promise<CalendarEvent>;
}
export class LocalDeliverySink implements EmailAdapter, MessagingAdapter {
  readonly emails: Email[] = [];
  readonly messages: Notification[] = [];
  private seen = new Map<string, { fingerprint: string; id: string }>();
  constructor(private capacity = 1000) {}
  private deliver(kind: string, value: unknown, intent: SendIntent) {
    SendIntentSchema.parse(intent);
    const key = `${kind}:${intent.idempotencyKey}`;
    const fingerprint = JSON.stringify(value);
    const previous = this.seen.get(key);
    if (previous) {
      if (previous.fingerprint !== fingerprint) throw new Error('Idempotency key conflict');
      return { id: previous.id, mode: 'local' as const, duplicate: true };
    }
    if (this.seen.size >= this.capacity) throw new Error('Local sink capacity reached');
    const id = crypto.randomUUID();
    this.seen.set(key, { fingerprint, id });
    return { id, mode: 'local' as const, duplicate: false };
  }
  async send(message: Email, intent: SendIntent) {
    const value = EmailSchema.parse(message);
    const receipt = this.deliver('email', value, intent);
    if (!receipt.duplicate) this.emails.push(value);
    return receipt;
  }
  async post(message: Notification, intent: SendIntent) {
    const value = NotificationSchema.parse(message);
    const receipt = this.deliver('message', value, intent);
    if (!receipt.duplicate) this.messages.push(value);
    return receipt;
  }
  reset() {
    this.emails.length = 0;
    this.messages.length = 0;
    this.seen.clear();
  }
}
export function validateWindow(from: string, to: string) {
  zonedDate.parse(from);
  zonedDate.parse(to);
  if (Date.parse(to) <= Date.parse(from)) throw new Error('Invalid time window');
}
export class FixtureCalendar implements CalendarAdapter {
  private events: CalendarEvent[];
  private keys = new Map<string, { value: string; event: CalendarEvent }>();
  constructor(events: CalendarEvent[] = []) {
    this.events = events.map((event) => ({
      ...CalendarEventInputSchema.parse(event),
      id: event.id,
      mode: 'fixture',
    }));
  }
  async list(from: string, to: string) {
    validateWindow(from, to);
    return structuredClone(
      this.events.filter(
        (event) =>
          Date.parse(event.end) > Date.parse(from) && Date.parse(event.start) < Date.parse(to),
      ),
    );
  }
  async create(input: CalendarEventInput, intent: SendIntent) {
    SendIntentSchema.parse(intent);
    const value = CalendarEventInputSchema.parse(input);
    const prior = this.keys.get(intent.idempotencyKey);
    if (prior) {
      if (prior.value !== JSON.stringify(value)) throw new Error('Idempotency key conflict');
      return structuredClone(prior.event);
    }
    if (this.events.length >= 1000) throw new Error('Fixture calendar capacity reached');
    const event: CalendarEvent = { ...value, id: crypto.randomUUID(), mode: 'fixture' };
    this.events.push(event);
    this.keys.set(intent.idempotencyKey, { value: JSON.stringify(value), event });
    return structuredClone(event);
  }
}
