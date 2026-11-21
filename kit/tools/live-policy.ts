import { z } from 'zod';
import { createLiveAI } from '../modules/ai/src/server';
export function configuredLiveAI(
  options: { enabled: boolean; confirmed: boolean; maxCalls: number },
  env: NodeJS.ProcessEnv = process.env,
) {
  if (!options.enabled || !options.confirmed)
    throw new Error(
      'Live usage requires both --live and --confirm-usage; requests may incur provider charges.',
    );
  z.number().int().min(1).max(10).parse(options.maxCalls);
  const provider = z.enum(['openai', 'anthropic']).parse(env.AI_PROVIDER ?? 'openai');
  const model = env.AI_MODEL;
  if (!model) throw new Error('Set AI_MODEL to an available model before enabling live usage.');
  const name = provider === 'openai' ? 'OPENAI_API_KEY' : 'ANTHROPIC_API_KEY',
    apiKey = env[name];
  if (!apiKey) throw new Error(`Missing ${name}; never paste it into a request or UI.`);
  const adapter = createLiveAI({ provider, apiKey, model, maxRetries: 0, timeoutMs: 15_000 });
  let calls = 0,
    active = false;
  async function generate(prompt: string, signal?: AbortSignal) {
    z.string().min(1).max(2000).parse(prompt);
    if (active) throw new Error('One live call may run at a time');
    if (calls >= options.maxCalls)
      throw new Error(
        'Live call budget exhausted; restart deliberately for another bounded session',
      );
    calls++;
    active = true;
    try {
      return await adapter.generate({ prompt, maxOutputTokens: 128, signal });
    } finally {
      active = false;
    }
  }
  return {
    generate,
    policy: {
      provider,
      model,
      maxCalls: options.maxCalls,
      maxInputCharacters: 2000,
      maxOutputTokens: 128,
      maxRetries: 0,
      concurrency: 1,
      estimatedCostUSD: null,
      costDisclosure:
        'Unknown monetary cost; operator authorizes this bounded request/token budget. Set account spending limits separately.',
    },
  };
}
