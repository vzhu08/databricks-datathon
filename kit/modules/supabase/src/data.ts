import type { SupabaseClient } from '@supabase/supabase-js';
import { z } from 'zod';
import { NoteSchema, NoteInputSchema, type NoteRepository } from './index';
import type { Database } from './database.types';
export function createSupabaseNotes(client: SupabaseClient<Database>): NoteRepository {
  return {
    async list() {
      const { data, error } = await client
        .from('kit_notes')
        .select('*')
        .order('created_at', { ascending: false })
        .limit(100);
      if (error) throw error;
      return z.array(NoteSchema).parse(data);
    },
    async create(input) {
      const { data: auth, error: authError } = await client.auth.getUser();
      if (authError || !auth.user) throw new Error('Sign in required');
      const { data, error } = await client
        .from('kit_notes')
        .insert({ ...NoteInputSchema.parse(input), owner_id: auth.user.id })
        .select()
        .single();
      if (error) throw error;
      return NoteSchema.parse(data);
    },
    async update(id, input) {
      z.uuid().parse(id);
      const { data, error } = await client
        .from('kit_notes')
        .update(NoteInputSchema.parse(input))
        .eq('id', id)
        .select()
        .single();
      if (error) throw error;
      return NoteSchema.parse(data);
    },
    async delete(id) {
      z.uuid().parse(id);
      const { data, error } = await client.from('kit_notes').delete().eq('id', id).select('id');
      if (error) throw error;
      if (!data.length) throw new Error('Note not found');
    },
  };
}
function ownedPath(userId: string, filename: string) {
  z.uuid().parse(userId);
  if (!/^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,119}$/.test(filename) || filename.includes('..'))
    throw new Error('Unsafe filename');
  return `${userId}/${filename}`;
}
export async function uploadOwnedFile(
  client: SupabaseClient<Database>,
  file: Blob,
  filename: string,
) {
  if (file.size > 5_000_000) throw new Error('File exceeds 5 MB');
  if (!['text/plain', 'application/pdf', 'image/png', 'image/jpeg'].includes(file.type))
    throw new Error('Unsupported content type');
  const { data: auth, error: authError } = await client.auth.getUser();
  if (authError || !auth.user) throw new Error('Sign in required');
  const path = ownedPath(auth.user.id, filename);
  const { data, error } = await client.storage
    .from('kit-private')
    .upload(path, file, { upsert: false, contentType: file.type });
  if (error) throw error;
  return data.path;
}
export async function signedFileUrl(client: SupabaseClient<Database>, path: string, seconds = 60) {
  z.number().int().min(1).max(600).parse(seconds);
  const { data, error } = await client.storage.from('kit-private').createSignedUrl(path, seconds);
  if (error) throw error;
  return data.signedUrl;
}
export async function downloadOwnedFile(client: SupabaseClient<Database>, path: string) {
  const { data, error } = await client.storage.from('kit-private').download(path);
  if (error) throw error;
  return data;
}
