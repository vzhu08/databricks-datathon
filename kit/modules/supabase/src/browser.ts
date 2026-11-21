import { createBrowserClient } from '@supabase/ssr';
import { SupabaseConfigSchema, type SupabaseConfig } from './index';
import type { Database } from './database.types';
export function createSupabaseBrowser(config: SupabaseConfig) {
  const value = SupabaseConfigSchema.parse(config);
  return createBrowserClient<Database>(value.url, value.publishableKey);
}
