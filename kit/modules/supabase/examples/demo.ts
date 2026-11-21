import { createLocalNotes, loadNotes } from '../src/index';
const notes = createLocalNotes('11111111-1111-4111-8111-111111111111');
console.log({ mode: 'fixture', state: await loadNotes(notes) });
const note = await notes.create({
  title: 'Hackathon demo',
  body: 'Owner-isolated local CRUD fixture.',
});
await notes.update(note.id, { title: 'Reviewed demo', body: note.body });
console.log({ mode: 'fixture', state: await loadNotes(notes) });
await notes.delete(note.id);
console.log({ mode: 'fixture', state: await loadNotes(notes) });
