import { writeFile, mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { normalizeText } from '../../documents/src/index';
import { toCSV } from '../src/index';
import { createPDFReport, createQRCode, ShareStore, shareResponse } from '../src/server';
import rows from '../fixtures/results.json';
const out = resolve(process.argv[2] ?? '.kit/exports-demo');
await mkdir(out, { recursive: true });
const document = normalizeText({
  filename: 'garden.txt',
  text: 'Community gardens supply fresh vegetables.',
});
const citation = {
  documentId: document.id,
  segmentId: document.segments[0]!.id,
  start: 0,
  end: document.text.length,
  quote: document.text,
};
await writeFile(resolve(out, 'results.csv'), toCSV(rows));
await writeFile(
  resolve(out, 'report.pdf'),
  await createPDFReport({
    title: 'Synthetic garden report',
    summary: 'A local evidence-linked demonstration.',
    documents: [document],
    citations: [citation],
    metadata: { mode: 'local synthetic fixture' },
  }),
);
await writeFile(resolve(out, 'qr.svg'), await createQRCode('https://example.org/share/demo'));
const store = new ShareStore();
const { token } = store.create({
  ownerId: 'demo-user',
  confirmed: true,
  value: {
    title: 'Synthetic garden report',
    summary: 'A deliberately shared sample',
    sources: [{ label: document.filename, quote: document.text }],
  },
});
await writeFile(resolve(out, 'shared-result.html'), await shareResponse(store, token).text());
console.log(
  JSON.stringify(
    {
      mode: 'local',
      outputDirectory: out,
      files: ['results.csv', 'report.pdf', 'qr.svg', 'shared-result.html'],
      note: 'QR uses example.org. HTML is a static sample; revocable URLs require the shareResponse route and store.',
    },
    null,
    2,
  ),
);
