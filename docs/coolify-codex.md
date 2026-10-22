# Postiz on Coolify with Codex OAuth

This fork supports `AI_TEXT_PROVIDER=codex` and `AI_IMAGE_PROVIDER=codex`
independently. Omit them (or use `openai`) to keep the upstream OpenAI API
behavior. There is no automatic fallback to a paid API when Codex fails.

The private `codex-bridge` service runs the pinned official Codex CLI. Text
requests use `codex exec`, JSON schemas and validated OpenAI-compatible chat
completion responses. Native image generation uses Codex app-server's public
stdio protocol and its `imageGeneration` completion item. Images count toward
Codex usage; they are not sent to the public OpenAI Images API in Codex mode.

## Deployment

In Coolify, deploy the fork branch `codex/coolify-codex-oauth` as a Docker Compose
application using `/docker-compose.coolify.yaml`. Route only the `postiz`
service, on port 5000. Use HTTPS.

Configure these private Coolify variables before deployment:

- `POSTIZ_URL`: public HTTPS origin without a trailing slash.
- `POSTIZ_JWT_SECRET`: a long random signing secret.
- `POSTIZ_DB_PASSWORD` and `TEMPORAL_DB_PASSWORD`: independent random passwords
  (URL-safe characters for the Postiz database URL).
- `CODEX_BRIDGE_TOKEN`: at least 32 random characters. This is a private service
  credential, **not** a ChatGPT token.

Coolify needs the interpolation variables at build time as well as runtime to
parse Compose. Keep `inject_build_args_to_dockerfile=false`; Dockerfiles do not
consume these secrets as build arguments, and `.env` files are excluded from
the build context. Keep Postgres, Redis, Elasticsearch, Temporal and the bridge
on the application network without published ports.

Postiz data, uploads, Temporal data and the Codex authentication cache each have
persistent volumes. Back up the database and uploads before upgrades. Do not
commit credentials, dump container environments, or print OAuth cache files.

`DISABLE_REGISTRATION=true` still permits the first account in upstream Postiz.
Create that first account before opening public routing. Afterward it prevents
public signups. Social networks still require their own developer applications,
OAuth client credentials and callback URLs.

## Connect ChatGPT on the server

Open a terminal in the `codex-bridge` container as its default `node` user:

```sh
/bridge/node_modules/.bin/codex login --device-auth -c 'cli_auth_credentials_store="file"'
/bridge/node_modules/.bin/codex login status
```

Open the displayed OpenAI URL in your own browser and enter the one-time code.
Enable device-code login in ChatGPT security settings if required. The login
cache lives only in the `codex-auth` volume. Codex manages token refresh; login
may be required again after revocation or account changes. Do not copy the
administrator's desktop authentication files into this deployment.

The bridge `/health` endpoint is a **liveness** check. It does not prove that
ChatGPT is signed in, has quota, or can generate images. Verify a real text and
image request after login. The bridge forces ChatGPT authentication and does
not inherit OpenAI API keys from the app.

## Supported behavior and limits

- Text: generation, rewriting, structured outputs, LangChain workflows, the
  Copilot editor and the Mastra assistant. Function calls are validated and
  returned to Postiz, whose existing authorization and confirmation flows
  execute them. Codex cannot execute those actions directly.
- Images: new images from a prompt, returned as PNG/base64 and stored through
  Postiz's normal media handling. Native Codex controls its image model and
  dimensions; requested dimensions are aspect-ratio guidance, not an exact
  pixel-size guarantee. Image editing is not exposed by this adapter yet.
- Voice, transcription and video generation retain their existing providers;
  configuring Codex does not replace ElevenLabs, Deepgram, FAL or RunPod.
- Image inputs to the text endpoint are rejected explicitly.
- Text streaming uses SSE keepalives while Codex generates; the validated final
  result is emitted in chunks afterward. It does not stream individual tokens.
- Two text generations and one image generation can run concurrently, with
  bounded queues. Busy, timeout, authentication and invalid-output failures
  return errors without exposing prompts, logs or credentials.
- The runtime disables shell, subagents, apps, plugins and web search. Only the
  image route enables the native image tool. Containers have no Docker socket
  or host mounts; the bridge is non-root with a read-only root filesystem.

Set `CODEX_MODEL` on the bridge if an explicit model is needed and available to
the signed-in account. Otherwise Codex selects its supported default. Model
names sent by upstream Postiz are compatibility labels and do not override it.

## Verification

```sh
cd services/codex-bridge
npm ci --ignore-scripts
npm test
```

These tests exercise the real OpenAI client against a mocked Codex runtime:
text, schemas, tool streaming, errors, auth, cancellation, concurrency and PNG
responses. They do not establish live OAuth or model availability. The Postiz
Docker build separately checks the backend, orchestrator and frontend.

After deployment and device login, run this inside the **Postiz** container
to check the actual compiled provider with its installed LangChain and Mastra
versions (this makes two small live requests and uses account quota):

```sh
cd /app
node services/codex-bridge/consumers.smoke.cjs
```

LangChain must retain an upstream chat model label: a label containing `codex`
can silently force its Responses API even when `useResponsesApi` is false.
The bridge still selects the actual Codex model independently.

References: [Codex authentication](https://learn.chatgpt.com/docs/auth),
[noninteractive mode](https://learn.chatgpt.com/docs/non-interactive-mode),
[app-server](https://learn.chatgpt.com/docs/app-server),
[image generation](https://learn.chatgpt.com/docs/image-generation).
