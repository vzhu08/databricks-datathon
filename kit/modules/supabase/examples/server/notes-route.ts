import { z } from 'zod';
import { KitError } from '../../../../packages/runtime/src/index';
import { readJSON } from '../../../../packages/runtime/src/body';
import { NoteInputSchema, type NoteRepository } from '../../src/index';

/** authorize must verify the request's session and return its RLS-backed repository. */
export function createNotesHandler(options: {
  siteUrl: string;
  authorize(request: Request): Promise<NoteRepository>;
}) {
  const origin = new URL(options.siteUrl).origin;
  return async (request: Request): Promise<Response> => {
    const json = (data: unknown, status = 200) =>
      Response.json(data, { status, headers: { 'cache-control': 'no-store' } });
    try {
      if (!['GET', 'POST', 'PATCH', 'DELETE'].includes(request.method))
        return json({ error: 'Method not allowed' }, 405);
      if (request.method !== 'GET' && request.headers.get('origin') !== origin)
        return json({ error: 'Invalid origin' }, 403);
      const repository = await options.authorize(request);
      if (request.method === 'GET') return json(await repository.list());
      if (request.method === 'POST')
        return json(
          await repository.create(await readJSON(request, NoteInputSchema.strict(), 210_000)),
          201,
        );
      const id = z.uuid().parse(new URL(request.url).searchParams.get('id'));
      if (request.method === 'PATCH')
        return json(
          await repository.update(id, await readJSON(request, NoteInputSchema.strict(), 210_000)),
        );
      await repository.delete(id);
      return json({ deleted: true });
    } catch (error) {
      if (error instanceof KitError) return json({ error: error.message }, error.status);
      if (error instanceof z.ZodError) return json({ error: 'Invalid note input' }, 400);
      return json({ error: 'Notes request failed. Check the session and retry.' }, 500);
    }
  };
}
