import { LocalDeliverySink, FixtureCalendar } from '../src/index';
const sink = new LocalDeliverySink();
const intent = { authorized: true as const, idempotencyKey: 'demo-message' };
console.log(
  await sink.send(
    {
      from: 'demo@example.test',
      to: ['judge@example.test'],
      subject: 'Local demo',
      text: 'No external email was sent.',
    },
    intent,
  ),
);
console.log(await sink.post({ channel: 'demo', text: 'The local fixture is ready.' }, intent));
const calendar = new FixtureCalendar();
console.log(
  await calendar.create(
    {
      summary: 'Demo rehearsal',
      start: '2026-10-09T10:00:00-04:00',
      end: '2026-10-09T10:30:00-04:00',
      timeZone: 'America/New_York',
    },
    intent,
  ),
);
