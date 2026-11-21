// Copy into proxy.ts at the Next.js app root and adjust the relative import.
import { NextRequest, NextResponse } from 'next/server';
import { createSupabaseServer } from '../src/server';
export async function proxy(request: NextRequest) {
  let response = NextResponse.next({ request });
  const client = createSupabaseServer(
    {
      url: process.env.NEXT_PUBLIC_SUPABASE_URL ?? '',
      publishableKey: process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ?? '',
    },
    {
      getAll: () => request.cookies.getAll(),
      setAll: (cookies) => {
        for (const cookie of cookies) request.cookies.set(cookie.name, cookie.value);
        response = NextResponse.next({ request });
        for (const { name, value, options } of cookies) response.cookies.set(name, value, options);
      },
    },
  );
  await client.auth.getUser();
  response.headers.set('cache-control', 'private, no-store');
  return response;
}
export const config = { matcher: ['/account/:path*', '/api/auth/:path*'] };
