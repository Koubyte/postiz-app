import OpenAI from 'openai';

export const usesCodex = () => process.env.AI_TEXT_PROVIDER === 'codex';

export const textAIConfigured = () =>
  usesCodex()
    ? !!process.env.CODEX_BRIDGE_URL && !!process.env.CODEX_BRIDGE_TOKEN
    : !!process.env.OPENAI_API_KEY;

// Codex credentials live only in the sidecar. This token authenticates the
// private bridge; it is never sent to OpenAI and is not a ChatGPT OAuth token.
export function textClientOptions() {
  if (!usesCodex()) return { apiKey: process.env.OPENAI_API_KEY || 'sk-proj-' };
  if (!textAIConfigured()) {
    throw new Error('Codex requires CODEX_BRIDGE_URL and CODEX_BRIDGE_TOKEN');
  }
  return {
    apiKey: process.env.CODEX_BRIDGE_TOKEN!,
    baseURL: process.env.CODEX_BRIDGE_URL!,
    timeout: 360000,
    maxRetries: 0,
  };
}

export const createTextClient = () => new OpenAI(textClientOptions());

export function textModelOptions(defaultModel: string) {
  const { apiKey, ...configuration } = textClientOptions();
  return {
    apiKey,
    // LangChain treats model names containing "codex" as Responses-only,
    // even with useResponsesApi=false. Keep the upstream compatibility label.
    model: defaultModel,
    ...(usesCodex() ? { configuration, useResponsesApi: false } : {}),
  };
}

export const usesCodexImages = () => process.env.AI_IMAGE_PROVIDER === 'codex';

export function createImageClient() {
  if (!usesCodexImages())
    return new OpenAI({ apiKey: process.env.OPENAI_API_KEY || 'sk-proj-' });
  if (!process.env.CODEX_BRIDGE_URL || !process.env.CODEX_BRIDGE_TOKEN) {
    throw new Error(
      'Codex images require CODEX_BRIDGE_URL and CODEX_BRIDGE_TOKEN'
    );
  }
  return new OpenAI({
    apiKey: process.env.CODEX_BRIDGE_TOKEN,
    baseURL: process.env.CODEX_BRIDGE_URL,
    timeout: 480000,
    maxRetries: 0,
  });
}

export async function generateCodexImage(prompt: string) {
  const result = await createImageClient().images.generate({
    model: 'codex',
    prompt,
    n: 1,
    size: '1024x1024',
    response_format: 'b64_json',
  });
  if (!result.data?.[0]?.b64_json) throw new Error('Codex returned no image');
  return 'data:image/png;base64,' + result.data[0].b64_json;
}
