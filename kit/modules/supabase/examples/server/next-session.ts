import { NextRequest, NextResponse } from 'next/server';
import type { SupabaseClient } from '@supabase/supabase-js';
import { createSupabaseServer } from '../../src/server';
import type { Database } from '../../src/database.types';

export async function withExampleSession(
  request: NextRequest,
  handler: (client: SupabaseClient<Database>) => Promise<Response>,
) {
  if (process.env.NEXT_PUBLIC_SUPABASE_EXAMPLE_MODE !== 'live')
    return NextResponse.json(
      { error: 'Live routes are disabled in fixture mode' },
      { status: 503, headers: { 'cache-control': 'no-store' } },
    );
  const outgoing = new NextResponse();
  try {
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
    const result = await handler(client);
    const response = new NextResponse(result.body, {
      status: result.status,
      headers: result.headers,
    });
    for (const cookie of outgoing.cookies.getAll()) response.cookies.set(cookie);
    response.headers.set('cache-control', 'no-store');
    return response;
  } catch {
    return NextResponse.json(
      { error: 'Supabase example is not configured or is unavailable' },
      { status: 503, headers: { 'cache-control': 'no-store' } },
    );
  }
}
