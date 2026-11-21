import { resetDemoShares } from '../../../../../document-workbench/routes/share';
import { resetDemoJobs } from '../../../../../media-assistant/routes/jobs';
import { authorizeDemoReset } from '../../../../../../packages/runtime/src/demo-reset';
import { errorResponse } from '../../../../../../packages/runtime/src/index';
export const runtime = 'nodejs';
export async function POST(request: Request) {
  try {
    authorizeDemoReset(request);
    resetDemoShares();
    resetDemoJobs();
    return Response.json({
      reset: ['local share links', 'local memory jobs'],
      next: 'Reload browser pages to restore synthetic samples. Restart npm run realtime to clear its separate rooms.',
    });
  } catch (e) {
    return errorResponse(e);
  }
}
