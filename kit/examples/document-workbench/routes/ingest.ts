import path from 'node:path';
import { ingestDocument } from '../../../modules/documents/src/server';
import { pythonOCR } from '../../../modules/documents/src/ocr-server';
import { KitError, errorResponse } from '../../../packages/runtime/src/index';
import { readRequestBytes } from '../../../packages/runtime/src/body';
export async function POST(request: Request) {
  try {
    let filename: string;
    try {
      filename = decodeURIComponent(request.headers.get('x-filename') ?? 'upload.txt');
    } catch {
      throw new KitError('INVALID_FILENAME', 'Filename must be URI-encoded UTF-8');
    }
    if (filename.length > 200) throw new KitError('INVALID_FILENAME', 'Filename is too long');
    const bytes = await readRequestBytes(request, 10_000_000);
    let ocr;
    if (process.env.KIT_OCR_ENABLED === 'true') {
      const python = process.env.KIT_OCR_PYTHON,
        worker = process.env.KIT_OCR_WORKER;
      if (!python || !worker || !path.isAbsolute(python) || !path.isAbsolute(worker))
        throw new KitError(
          'OCR_CONFIGURATION',
          'Set absolute KIT_OCR_PYTHON and KIT_OCR_WORKER paths on the server',
          503,
        );
      ocr = pythonOCR({ python, worker, timeoutMs: 60_000 });
    }
    const document = await ingestDocument({ filename, bytes }, { ocr, signal: request.signal });
    return Response.json(document, { headers: { 'cache-control': 'no-store' } });
  } catch (error) {
    return errorResponse(error);
  }
}
