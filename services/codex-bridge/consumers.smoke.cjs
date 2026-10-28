// Run inside the built Postiz container after device login. Uses live quota.
const assert = require('node:assert/strict');
const { ChatOpenAI } = require('@langchain/openai');
const { Agent } = require('@mastra/core/agent');
const { createOpenAI } = require('@ai-sdk/openai');
const { z } = require('zod');
const provider = require('../../apps/backend/dist/libraries/nestjs-libraries/src/openai/text-provider.js');

async function main() {
  assert(provider.usesCodex(), 'Run with AI_TEXT_PROVIDER=codex');
  const options = provider.textModelOptions('gpt-4.1');
  assert.equal(options.model, 'gpt-4.1');
  const model = new ChatOpenAI(options);
  // This catches LangChain silently selecting Responses despite its flag.
  const structured = await model
    .withStructuredOutput(z.object({ greeting: z.string() }))
    .invoke('Return a brief greeting in French.');
  assert(structured.greeting.length > 0);
  console.log('LangChain structured output: OK');

  const agent = new Agent({
    id: 'codex-smoke', name: 'Codex smoke test',
    instructions: 'Reply briefly in French.',
    model: createOpenAI(provider.textClientOptions()).chat('codex'),
  });
  const result = await agent.generate('Say hello.');
  assert(result.text.length > 0);
  console.log('Mastra agent: OK');
}

main().catch(() => {
  console.error('Consumer smoke test failed; check provider configuration and login.');
  process.exitCode = 1;
});
