import type { NextRequest } from 'next/server';
import { handleAuthRequest } from '../../../../src/server';
import { withExampleSession } from '../../../server/next-session';
export const runtime = 'nodejs';
function handler(request: NextRequest) {
  return withExampleSession(request, (client) =>
    handleAuthRequest(request, client, process.env.SITE_URL ?? 'http://127.0.0.1:3004'),
  );
}
export { handler as GET, handler as POST };
