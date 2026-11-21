import { createHash, randomBytes } from 'node:crypto';
import { PDFDocument, StandardFonts, rgb } from 'pdf-lib';
import QRCode from 'qrcode';
import { z } from 'zod';
import {
  validateDocument,
  validateCitation,
  type Citation,
  type NormalizedDocument,
} from '../../../packages/contracts/src/index';
import { escapeHTML } from './index';
export type PDFReport = {
  title: string;
  summary?: string;
  documents: NormalizedDocument[];
  citations: Citation[];
  metadata?: Record<string, string>;
};
export async function createPDFReport(input: PDFReport): Promise<Uint8Array> {
  z.string().min(1).max(200).parse(input.title);
  const documents = input.documents.map(validateDocument);
  if (input.citations.some((c) => !validateCitation(c, documents)))
    throw new Error('Report contains unsupported citations');
  const pdf = await PDFDocument.create();
  const font = await pdf.embedFont(StandardFonts.Helvetica);
  pdf.setTitle(input.title);
  pdf.setProducer('Hackathon Kit');
  pdf.setSubject('Evidence-linked report');
  let page = pdf.addPage([612, 792]),
    y = 740;
  const printable = (text: string) =>
    Array.from(text)
      .map((c) => {
        try {
          font.encodeText(c);
          return c;
        } catch {
          return '?';
        }
      })
      .join('');
  const line = (text: string, size = 11) => {
    if (y < 52) {
      page = pdf.addPage([612, 792]);
      y = 740;
    }
    page.drawText(text, { x: 48, y, size, font, color: rgb(0.12, 0.16, 0.22) });
    y -= size + 6;
  };
  const paragraph = (value: string, size = 11) => {
    for (const raw of printable(value).split('\n')) {
      let current = '';
      for (const word of raw.split(/\s+/)) {
        const candidate = current ? `${current} ${word}` : word;
        if (font.widthOfTextAtSize(candidate, size) <= 516) {
          current = candidate;
          continue;
        }
        if (current) line(current, size);
        current = '';
        for (const char of word) {
          if (font.widthOfTextAtSize(current + char, size) > 516) {
            line(current, size);
            current = '';
          }
          current += char;
        }
      }
      line(current, size);
    }
    y -= 6;
  };
  paragraph(input.title, 22);
  if (input.summary) paragraph(z.string().max(100_000).parse(input.summary));
  for (const [key, value] of Object.entries(input.metadata ?? {})) paragraph(`${key}: ${value}`);
  paragraph('Sources and evidence', 16);
  for (const [n, citation] of input.citations.entries()) {
    const document = documents.find((d) => d.id === citation.documentId)!;
    const segment = document.segments.find((s) => s.id === citation.segmentId);
    paragraph(
      `[${n + 1}] ${document.filename}${segment?.page ? `, page ${segment.page}` : ''}${segment?.row ? `, row ${segment.row}` : ''}${segment?.section ? `, ${segment.section}` : ''}`,
    );
    paragraph(citation.quote);
    paragraph(
      `Source: ${document.id}; UTF-16 span ${citation.start}-${citation.end}; hash ${document.hash}`,
      8,
    );
  }
  paragraph(
    'Exact source evidence and provenance are attached to this report as evidence.json.',
    8,
  );
  for (const [n, reportPage] of pdf.getPages().entries())
    reportPage.drawText(`Page ${n + 1} of ${pdf.getPageCount()}`, {
      x: 48,
      y: 28,
      size: 8,
      font,
      color: rgb(0.4, 0.4, 0.4),
    });
  await pdf.attach(
    Buffer.from(
      JSON.stringify(
        {
          title: input.title,
          citations: input.citations,
          sources: documents.map(({ id, filename, mimeType, hash, metadata }) => ({
            id,
            filename,
            mimeType,
            hash,
            metadata,
          })),
          metadata: input.metadata ?? {},
          offsetEncoding: 'utf-16',
        },
        null,
        2,
      ),
    ),
    'evidence.json',
    { mimeType: 'application/json', description: 'Exact citation spans and provenance' },
  );
  return pdf.save();
}
export async function createQRCode(url: string): Promise<string> {
  const parsed = new URL(z.string().max(2000).parse(url));
  if (!['https:', 'http:'].includes(parsed.protocol) || parsed.username || parsed.password)
    throw new Error('QR target must be a credential-free HTTP(S) URL');
  return QRCode.toString(parsed.href, {
    type: 'svg',
    errorCorrectionLevel: 'M',
    margin: 4,
    width: 256,
  });
}
const SharedResultSchema = z
  .object({
    title: z.string().min(1).max(200),
    summary: z.string().max(100_000),
    sources: z
      .array(z.object({ label: z.string(), quote: z.string() }))
      .max(100)
      .default([]),
  })
  .strict();
export type SharedResult = z.input<typeof SharedResultSchema>;
type Share = { ownerId: string; value: z.output<typeof SharedResultSchema>; expires: number };
/** Instance-local demo store. Production uses a persistent equivalent with the same owner checks. */
export class ShareStore {
  private shares = new Map<string, Share>();
  constructor(private options: { maxEntries?: number; now?: () => number } = {}) {}
  private now() {
    return this.options.now?.() ?? Date.now();
  }
  private key(token: string) {
    return createHash('sha256').update(token).digest('hex');
  }
  private purge() {
    for (const [key, share] of this.shares)
      if (share.expires <= this.now()) this.shares.delete(key);
  }
  create(input: { ownerId: string; value: SharedResult; ttlMs?: number; confirmed: boolean }) {
    if (!input.ownerId || input.confirmed !== true)
      throw new Error('Owner and explicit share confirmation required');
    const ttl = z
      .number()
      .int()
      .min(1000)
      .max(7 * 86400_000)
      .parse(input.ttlMs ?? 3600_000);
    const value = SharedResultSchema.parse(input.value);
    this.purge();
    if (this.shares.size >= (this.options.maxEntries ?? 100))
      throw new Error('Share store is full');
    const token = randomBytes(32).toString('base64url'),
      expires = this.now() + ttl;
    this.shares.set(this.key(token), { ownerId: input.ownerId, value, expires });
    return { token, expiresAt: new Date(expires).toISOString() };
  }
  get(token: string) {
    this.purge();
    const share = this.shares.get(this.key(token));
    return share ? structuredClone(share.value) : null;
  }
  revoke(token: string, ownerId: string): boolean {
    const key = this.key(token),
      share = this.shares.get(key);
    if (!share) return false;
    if (share.ownerId !== ownerId) throw new Error('Share owner mismatch');
    return this.shares.delete(key);
  }
}
export function shareResponse(store: ShareStore, token: string): Response {
  const result = store.get(token);
  const headers = {
    'content-type': 'text/html; charset=utf-8',
    'cache-control': 'no-store',
    'referrer-policy': 'no-referrer',
    'x-robots-tag': 'noindex, nofollow',
    'content-security-policy':
      "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
  };
  if (!result)
    return new Response('This share has expired or was revoked.', { status: 404, headers });
  return new Response(
    `<!doctype html><html lang="en"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHTML(result.title)}</title><style>body{font:18px system-ui;max-width:760px;margin:4rem auto;padding:1rem;line-height:1.6}blockquote{border-left:3px solid #777;padding-left:1rem}</style><main><p>Shared result</p><h1>${escapeHTML(result.title)}</h1><p>${escapeHTML(result.summary)}</p>${result.sources.map((s) => `<section><h2>${escapeHTML(s.label)}</h2><blockquote>${escapeHTML(s.quote)}</blockquote></section>`).join('')}</main></html>`,
    { headers },
  );
}
