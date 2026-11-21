import { createPDFReport } from '../../../modules/exports/src/server';
import { DocumentSchema, CitationSchema } from '../../../packages/contracts/src/index';
import { errorResponse } from '../../../packages/runtime/src/index';
import { z } from 'zod';
import { readJSON } from '../../../packages/runtime/src/body';
export async function POST(request: Request) {
  try {
    const body = await readJSON(
      request,
      z.object({
        title: z.string().max(200),
        summary: z.string().max(10_000).optional(),
        documents: z.array(DocumentSchema).max(10),
        citations: z.array(CitationSchema).max(100),
      }),
      500_000,
    );
    const bytes = await createPDFReport(body);
    return new Response(new Uint8Array(bytes), {
      headers: {
        'content-type': 'application/pdf',
        'content-disposition': 'attachment; filename="report.pdf"',
        'cache-control': 'no-store',
      },
    });
  } catch (error) {
    return errorResponse(error);
  }
}
