import { errorResponse, transformText } from '@kit/runtime';
import { TransformRequestSchema } from '@kit/contracts';
import { readJSON } from '@kit/body';
export async function POST(request: Request) {
  const id = crypto.randomUUID();
  try {
    const result = transformText(await readJSON(request, TransformRequestSchema));
    console.info(
      JSON.stringify({ requestId: id, event: 'transform', characters: result.characters }),
    );
    return Response.json(result, { headers: { 'x-request-id': id, 'cache-control': 'no-store' } });
  } catch (error) {
    return errorResponse(error, id);
  }
}
