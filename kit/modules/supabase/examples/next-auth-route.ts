// Copy this file into app/api/auth/route.ts and adjust the relative module import.
import { NextRequest, NextResponse } from 'next/server';
import { createSupabaseServer, handleAuthRequest } from '../src/server';
async function handler(request: NextRequest) {
  const outgoing = new NextResponse();
  const client = createSupabaseServer(
    {
      url: process.env.NEXT_PUBLIC_SUPABASE_URL ?? '',
      publishableKey: process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ?? '',
    },
    {
      getAll: () => request.cookies.getAll(),
      setAll: (cookies) => {
        for (const { name, value, options } of cookies) {
          request.cookies.set(name, value);
          outgoing.cookies.set(name, value, options);
        }
      },
    },
  );
  const result = await handleAuthRequest(
    request,
    client,
    process.env.SITE_URL ?? 'http://localhost:3000',
  );
  const response = new NextResponse(result.body, {
    status: result.status,
    headers: result.headers,
  });
  for (const cookie of outgoing.cookies.getAll()) response.cookies.set(cookie);
  response.headers.set('cache-control', 'no-store');
  return response;
}
export { handler as GET, handler as POST };
