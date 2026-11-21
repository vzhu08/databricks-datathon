import { TransformRequestSchema } from '../../packages/contracts/src/index';
import { errorResponse } from '../../packages/runtime/src/index';
import { readJSON } from '../../packages/runtime/src/body';
import { transformWithPython } from './client-example';
export async function POST(request: Request) {
  try {
    const input = await readJSON(request, TransformRequestSchema);
    return Response.json(await transformWithPython(input.text, undefined, request.signal), {
      headers: { 'cache-control': 'no-store' },
    });
  } catch (error) {
    return errorResponse(error);
  }
}
