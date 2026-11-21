import { createServerClient, type CookieMethodsServer } from '@supabase/ssr';
import type { SupabaseClient } from '@supabase/supabase-js';
import { z } from 'zod';
import { readJSON } from '../../../packages/runtime/src/body';
import { KitError } from '../../../packages/runtime/src/index';
import { SupabaseConfigSchema, type SupabaseConfig } from './index';
import type { Database } from './database.types';
export function createSupabaseServer(config: SupabaseConfig, cookies: CookieMethodsServer) {
  const value = SupabaseConfigSchema.parse(config);
  return createServerClient<Database>(value.url, value.publishableKey, { cookies });
}
export async function requireUser(client: SupabaseClient<Database>) {
  const { data, error } = await client.auth.getUser();
  if (error || !data.user) throw new Error('Sign in required');
  return data.user;
}
/** JSON endpoint, registered by the application. Cookies must be forwarded to the outgoing response. */
export async function handleAuthRequest(
  request: Request,
  client: SupabaseClient<Database>,
  siteUrl: string,
): Promise<Response> {
  const site = new URL(siteUrl);
  const requestUrl = new URL(request.url);
  const action = requestUrl.searchParams.get('action') ?? 'session';
  try {
    if (request.method === 'POST' && request.headers.get('origin') !== site.origin)
      return Response.json({ error: 'Invalid origin' }, { status: 403 });
    if (action === 'signin' && request.method === 'POST') {
      const input = await readJSON(
        request,
        z.object({ email: z.email(), password: z.string().min(1).max(1000) }),
        5000,
      );
      const { data, error } = await client.auth.signInWithPassword(input);
      if (error) throw new Error('Sign in failed');
      return Response.json(
        { user: data.user ? { id: data.user.id, email: data.user.email } : null },
        { headers: { 'cache-control': 'no-store' } },
      );
    }
    if (action === 'signout' && request.method === 'POST') {
      const { error } = await client.auth.signOut();
      if (error) throw error;
      return Response.json({ signedOut: true });
    }
    if (action === 'oauth' && request.method === 'GET') {
      const { data, error } = await client.auth.signInWithOAuth({
        provider: 'github',
        options: {
          redirectTo: new URL('/api/auth?action=callback', site).href,
          skipBrowserRedirect: true,
        },
      });
      if (error || !data.url) throw error ?? new Error('OAuth URL missing');
      return Response.redirect(data.url, 303);
    }
    if (action === 'callback' && request.method === 'GET') {
      const code = requestUrl.searchParams.get('code');
      if (!code) throw new Error('OAuth code missing');
      const { error } = await client.auth.exchangeCodeForSession(code);
      if (error) throw new Error('OAuth exchange failed');
      return Response.redirect(new URL('/', site), 303);
    }
    if (action === 'session' && request.method === 'GET') {
      const { data, error } = await client.auth.getUser();
      return Response.json(
        { user: error || !data.user ? null : { id: data.user.id, email: data.user.email } },
        { headers: { 'cache-control': 'no-store' } },
      );
    }
    return Response.json({ error: 'Unknown auth action or method' }, { status: 405 });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : 'Authentication failed' },
      { status: error instanceof KitError ? error.status : 400 },
    );
  }
}
