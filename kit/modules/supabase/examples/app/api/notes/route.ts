import type { NextRequest } from 'next/server';
import { createSupabaseNotes } from '../../../../src/data';
import { requireUser } from '../../../../src/server';
import { KitError } from '../../../../../../packages/runtime/src/index';
import { createNotesHandler } from '../../../server/notes-route';
import { withExampleSession } from '../../../server/next-session';
export const runtime = 'nodejs';
function handler(request: NextRequest) {
  return withExampleSession(request, (client) =>
    createNotesHandler({
      siteUrl: process.env.SITE_URL ?? 'http://127.0.0.1:3004',
      async authorize() {
        try {
          await requireUser(client);
        } catch {
          throw new KitError('unauthorized', 'Sign in required', 401);
        }
        return createSupabaseNotes(client);
      },
    })(request),
  );
}
export { handler as GET, handler as POST, handler as PATCH, handler as DELETE };
