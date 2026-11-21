import { describe, it, expect } from 'vitest';
import { toCSV } from '../src/index';
import { createPDFReport, createQRCode, ShareStore, shareResponse } from '../src/server';
import { normalizeText } from '../../documents/src/index';
import { ingestDocument } from '../../documents/src/server';
describe('exports and deliberate sharing', () => {
  it('escapes formulas including control-prefix evasion and CSV quoting', () => {
    const csv = toCSV([{ a: '=1+1', b: ' \t@sum(A1)', c: 'line\n"quoted"', d: -2 }]);
    expect(csv).toContain('"\'=1+1"');
    expect(csv).toContain('"\' \t@sum(A1)"');
    expect(csv).toContain('"line\n""quoted"""');
    expect(csv).toContain('"-2"');
    expect(toCSV([])).toBe('');
  });
  it('creates downloadable PDF with citation content and rejects forged citations', async () => {
    const d = normalizeText({ filename: 'garden.txt', text: 'Gardens need water.' });
    const c = {
      documentId: d.id,
      segmentId: d.segments[0]!.id,
      start: 0,
      end: d.text.length,
      quote: d.text,
    };
    const bytes = await createPDFReport({
      title: 'Garden report',
      summary: 'Synthetic report',
      documents: [d],
      citations: [c],
    });
    const parsed = await ingestDocument({ filename: 'report.pdf', bytes });
    expect(parsed.text).toContain('Garden report');
    expect(parsed.text).toContain('Gardens need water.');
    expect(parsed.text).toContain('garden.txt');
    await expect(
      createPDFReport({ title: 'Bad', documents: [d], citations: [{ ...c, quote: 'Invented' }] }),
    ).rejects.toThrow('unsupported');
  });
  it('creates QR SVG only for valid web URLs', async () => {
    expect(await createQRCode('https://example.org/share/token')).toContain('<svg');
    await expect(createQRCode('javascript:alert(1)')).rejects.toThrow();
  });
  it('enforces explicit share consent, expiry, revocation and owner checks', () => {
    let now = 1000;
    const store = new ShareStore({ now: () => now, maxEntries: 2 });
    expect(() =>
      store.create({ ownerId: 'a', confirmed: false, value: { title: 'T', summary: 'S' } }),
    ).toThrow('confirmation');
    const link = store.create({
      ownerId: 'a',
      confirmed: true,
      value: { title: 'T', summary: 'S' },
      ttlMs: 1000,
    });
    expect(store.get(link.token)!.summary).toBe('S');
    expect(() => store.revoke(link.token, 'b')).toThrow('owner');
    now = 2000;
    expect(store.get(link.token)).toBeNull();
    const next = store.create({
      ownerId: 'a',
      confirmed: true,
      value: { title: 'T', summary: 'S' },
    });
    expect(store.revoke(next.token, 'a')).toBe(true);
    expect(store.get(next.token)).toBeNull();
  });
  it('renders escaped share pages with no-store and expires safely', async () => {
    const store = new ShareStore();
    const { token } = store.create({
      ownerId: 'a',
      confirmed: true,
      value: { title: '<script>x</script>', summary: 'Private choice deliberately shared' },
    });
    const response = shareResponse(store, token);
    expect(await response.text()).toContain('&lt;script&gt;');
    expect(response.headers.get('cache-control')).toBe('no-store');
    expect(shareResponse(store, 'invalid').status).toBe(404);
  });
});
