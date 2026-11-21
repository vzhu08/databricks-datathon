import { demoOrigin } from '../../../packages/runtime/src/demo-reset';
import { ShareStore, shareResponse } from '../../../modules/exports/src/server';
import { readJSON } from '../../../packages/runtime/src/body';
import { KitError, errorResponse } from '../../../packages/runtime/src/index';
import {
  DocumentSchema,
  CitationSchema,
  validateCitation,
} from '../../../packages/contracts/src/index';
import { z } from 'zod';
const globals = globalThis as typeof globalThis & { kitDemoShares?: ShareStore };
let store = (globals.kitDemoShares ??= new ShareStore());
export function resetDemoShares() {
  store = new ShareStore();
  globals.kitDemoShares = store;
}
const cookieName = 'kit-share-owner';
const owner = (request: Request) =>
  request.headers
    .get('cookie')
    ?.split(';')
    .map((s) => s.trim())
    .find((s) => s.startsWith(cookieName + '='))
    ?.slice(cookieName.length + 1);
export async function POST(request: Request) {
  store = globals.kitDemoShares!;
  try {
    const url = new URL(request.url);
    if (!['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))
      throw new KitError(
        'DEMO_ONLY',
        'Local sharing demo requires a loopback host; add authenticated persistent sharing for deployment.',
        403,
      );
    if (request.headers.get('origin') !== demoOrigin(request))
      throw new KitError('ORIGIN', 'Same-origin action required', 403);
    const input = await readJSON(
      request,
      z
        .object({
          title: z.string().min(1).max(200),
          summary: z.string().max(10_000),
          documents: z.array(DocumentSchema).max(10),
          citations: z.array(CitationSchema).max(100),
          confirmed: z.literal(true),
        })
        .strict(),
      500_000,
    );
    if (input.citations.some((c) => !validateCitation(c, input.documents)))
      throw new KitError('INVALID_EVIDENCE', 'Share contains unsupported evidence');
    const ownerId = owner(request) ?? crypto.randomUUID();
    const share = store.create({
      ownerId,
      value: {
        title: input.title,
        summary: input.summary,
        sources: input.citations.map((c) => ({
          label: input.documents.find((d) => d.id === c.documentId)!.filename,
          quote: c.quote,
        })),
      },
      confirmed: true,
      ttlMs: 3_600_000,
    });
    return Response.json(
      {
        url: `/api/kit/share?token=${encodeURIComponent(share.token)}`,
        expiresAt: share.expiresAt,
        mode: 'local',
        durability: 'process-memory',
      },
      {
        headers: {
          'set-cookie': `${cookieName}=${ownerId}; HttpOnly; SameSite=Strict; Path=/api/kit/share; Max-Age=3600`,
          'cache-control': 'no-store',
        },
      },
    );
  } catch (e) {
    return errorResponse(e);
  }
}
export async function GET(request: Request) {
  store = globals.kitDemoShares!;
  return shareResponse(store, new URL(request.url).searchParams.get('token') ?? '');
}
export async function DELETE(request: Request) {
  store = globals.kitDemoShares!;
  try {
    const url = new URL(request.url);
    if (request.headers.get('origin') !== demoOrigin(request))
      throw new KitError('ORIGIN', 'Same-origin action required', 403);
    const ownerId = owner(request);
    if (!ownerId) throw new KitError('OWNER', 'Owner session required', 403);
    store.revoke(url.searchParams.get('token') ?? '', ownerId);
    return Response.json({ revoked: true }, { headers: { 'cache-control': 'no-store' } });
  } catch (e) {
    return errorResponse(e);
  }
}
