# Planète Laser editorial studio

The approved `pl-social-v1` charter is applied by the deterministic media renderer.
The studio lives at `/editorial/` on the Postiz origin and authenticates each
private request against Postiz `/api/user/self`. Only the configured owner and
organization may approve. CSRF requires the exact origin and an action header.
No extra administrator password or browser API key is created.

One persistent SQLite/WAL volume holds weekly plans, immutable audit snapshots,
requests, jobs, exact-version approvals, deliveries, published blog projections,
and source/generated/composited media. Back up the entire volume using SQLite's
backup API for the database and a consistent media snapshot. Do not delete it
when upgrading the container. Keep exactly one uvicorn process per volume.

Every Friday at 09:00 Europe/Paris (with weekend catch-up), a unique plan for the
following Monday is prepared. Seven subjects, each adapted to Facebook and
Instagram, include at least three distinct products. One blog article belongs to
the same week. The owner approves the PLAN to start drafting, then approves each
finished item (both social captions, image and date displayed) before delivery.
The pause button stops new preparation and delivery; work already in flight can
finish. Missed delivery slots older than 30 minutes are blocked for rescheduling.

Adding a product request only adds it to the pending queue. The owner can revise
one selected plan slot with an instruction and/or pending product request before
approving the plan. A durable job changes only that brief, retaining the other
six briefs, blog and schedule. Stale/concurrent changes are rejected; failure
keeps the previous plan. Replaced requests return to the pending queue, and the
minimum of three distinct products remains enforced. After drafting, individual
content edits or correction requests invalidate only that item’s approval.

Drafting has no publishing tools. The separate delivery path rechecks exact
revision/hash, source media hashes, catalogue prices when displayed, and stock
status. Altering content/date clears approval; visual title changes rerender.
Publication is never inferred from plan approval or model output. Retries of
research and generation are bounded to two attempts, then explicit manual retry.
An ambiguous Postiz create request is marked uncertain and NEVER automatically
retried. Review Postiz before deciding whether to create a replacement. Delivery
is marked published only after Postiz reports PUBLISHED on both networks.

The public blog feed `/editorial/public/articles` contains only published
projections. Draft/source/generated media require the owner's session. Only the actual
published article cover is available from `/editorial/public/media/...`.
The storefront merges this feed with its two historical guides. Social posts do
not automatically link an unpublished article; they are useful standalone
adaptations. Statistics-driven topic optimization is not part of this version.

Product images use reference-guided generation through the Codex OAuth image
bridge. The exact product photograph is supplied to the generator to create a
complete, coherent scene with that product. The renderer never cuts out or pastes
a product: it only crops/resizes the resulting scene and applies the approved
logo, typography, palette and optional verified price. For a product, rendering
requires the reference bytes and an explicit acknowledgement that the generator
received them; missing references and supplier image restrictions block output.

The private reference photograph and generated scene are retained with SHA-256
provenance, alongside social and blog exports. Generation can change product
details even with a reference, so the owner must compare the source and scene and
approve product fidelity and image rights before publication. A successful
render is not a fidelity certification. Advice scenes can be generated without
a product reference; a depiction of the actual shop still requires a real photo.
No segmentation model, ONNX runtime or product compositing is used.

Environment:
- PUBLIC_URL: Postiz HTTPS origin, no trailing slash.
- POSTIZ_INTERNAL_URL: trusted private Postiz HTTP origin.
- POSTIZ_API_KEY, POSTIZ_ORG_ID, POSTIZ_CHANNELS (JSON facebook/instagram IDs).
- EDITORIAL_OWNER_EMAIL: existing Postiz owner.
- CODEX_BRIDGE_URL, CODEX_BRIDGE_TOKEN: existing private inference service.
- EDITORIAL_DATA=/data; EDITORIAL_WORKER=true (false for test servers).

Tests (isolated dependencies, no publishing):
```
python -m pytest services/editorial/test_media.py services/editorial/test_workflow.py
```

The Planète Laser storefront feed implementation lives in Koubyte/PL-v2.
Service changes are in docker-compose.coolify.yaml. Keep its canonical Coolify
private variables configured before a full application rebuild. Only the studio
service needs rebuilding for a studio-only update.


Product research separates model identity from variant and photo evidence. A missing
EAN or photo never makes a sourced model unknown. Variant/media uncertainty is
shown on the plan and blocks only image production until resolved.
`reviewed_products.py` keeps inspected manufacturer references (source and review
date); the HD-300 sky-blue nickname requires an explicit Bay Blue clarification.
Up to three reference photos are passed in order to the image bridge. Every
attachment must be acknowledged by its SHA-256; all reference files are retained
for review and sealed with the final approved visual. No cutout/compositing occurs.

Manual scheduling is independent of the plan week: the daily Monday–Sunday
spread is a default only. Social posts and the blog can be moved to any explicit
date, including the same day or before the batch week, in Europe/Paris. Saving
a date does not approve or generate content; past dates still block approval.

Approved social revisions are transferred immediately to Postiz with type=schedule
and the exact approved date. Only due/late-within-30-minutes posts use type=now.
Unapproved, rejected and failed revisions never enter the calendar. Blog projection
remains due-time gated. Reconciliation accepts Postiz's postId response and covers
future scheduled dates. Studio pause stops new transfers; existing Postiz schedules
must be changed/cancelled in Postiz.

## On-demand conversations

`/editorial/#discussion` is the mobile-friendly chat inside the Postiz origin;
Postiz's **Studio IA** navigation entry opens it using the existing owner session.
Conversations, messages, reference photos and `demand_items` are separate from
weekly plans. A brief can propose up to five additional social subjects. Each
proposal displays its date (Paris), optional owner-confirmed price and reference
photos. Preparing it creates a draft and a reference-guided visual; it never
approves or publishes anything. A correction is bound to the explicitly selected
on-demand post and its revision. All other posts remain unchanged.

Jobs, message nonces and proposal acceptance markers are durable/idempotent.
Inference only returns replies/briefs; it has no delivery authority. Generated
content uses the existing review, media provenance, hash and approval pipeline.
The owner must approve the exact final captions, visual and date. Direct edits
or regeneration revoke approval. Already transferred posts are managed in Postiz.

Additional posts reserve at least **120 minutes** between different subjects,
including weekly plans, pending studio drafts, and queued/published native Postiz
posts. Facebook and Instagram variants of the same subject share their slot.
A conflicting requested time advances to the next available slot (09:00 next day
if a shift passes 21:00 Paris). The resulting time is shown before approval.
Approval and delivery recheck the calendar and block on newly introduced conflicts,
rather than silently moving an approved post. The native Postiz editor itself can
still be used to schedule close posts manually; this guard applies to studio
on-demand preparation and delivery. Supported planning horizon: 90 days.

The microphone uses MediaRecorder with runtime WebM/MP4 support detection. Dictation
stops at 175 seconds or when the page goes into the background. It is transcribed
by the private `services/transcription` Faster Whisper service on CPU (medium model,
int8, two threads, 3 GiB limit). The text goes into the editable composer, never
automatically to the agent. Speech is not retained. Recording permission denial,
silence, unavailable model, unsupported browser and oversized audio leave typing
available. Production microphone hardware needs checking on the user's actual
phone; browser and container checks cannot certify every device.

`TRANSCRIPTION_URL=http://transcription:8789` is private, without host port or public
route. It authenticates service calls with the existing bridge secret passed as
`TRANSCRIPTION_TOKEN`; no paid speech API or new browser credential is used.
The model is downloaded at image build time and runtime is offline. JPEG/PNG/WebP
and iPhone HEIC references are normalized, metadata stripped and stored privately.
The chat sees filenames/descriptions; photo pixels are passed to the image generator,
not the text-only inference bridge. It must ask for a product name when unspecified.

Validation: `python -m pytest services/editorial/test_conversation.py
services/editorial/test_workflow.py services/editorial/test_media.py` plus browser
checks and a server transcription fixture. No live smoke test approves a post.

## Grok Bot community-manager connector

`/editorial/connect` is the owner-only setup workflow (the shell is public; all
configuration and key operations require the existing Postiz owner session and
CSRF protection). Add its Remote HTTPS MCP URL to Grok Bot with an Authorization
header. The owner generates a random 288-bit token, shown once; only its SHA-256
hash is persisted. Rotation/revocation takes effect on the next HTTP request.
The setup page provides the complete French bot instructions and last-use status.
Do not paste the token into chat, source files, URLs or logs.

The MCP SDK serves stateless Streamable HTTP at `/editorial/agent/mcp`, behind a
separate bearer gate. It exposes eight tools:
`get_editorial_context`, `get_content`, `get_visual`, `prepare_content`,
`revise_content`, `prepare_week`, `schedule_content` and `approve_content`.
It has no arbitrary HTTP, shell, filesystem or administrative tool. Its token cannot authenticate
any owner API. Origins, hosts, body sizes and queued-work limits are checked.

`prepare_content` queues one social subject (both Facebook and Instagram) or
one illustrated blog article through the existing Codex pipeline. A product
query triggers catalogue/manufacturer research; Grok can supply a real reference
image URL and source page from its own research. Images still use the bounded,
SSRF-safe fetcher, decoding checks and mandatory owner visual review. No source
restriction is bypassed. Posts respect the 120-minute calendar spacing; blog
articles use their own requested time and never require social calendar access.
Brouillons remain private and the existing site feed only exposes approved,
published articles. The discussion UI also accepts blog proposals and opens
specific review cards via the connector's `review_url`.

Every creation/correction requires a unique request_id. Durable payload hashes
prevent duplicate work after retries and reject reuse with changed arguments.
Corrections require the current revision and an unapproved, undelivered item;
only that draft is changed. A correction preserves its product and date. New
product/date requests should be submitted as a new brief or changed by the owner.
The existing Friday weekly scheduler remains the single schedule authority:
prepare_week returns the existing next week if present, avoiding duplicate
weekly content. Weekly plan approval and final-content approval remain
human actions, with the explicit companion-article exception below. Grok's voice interface is used for spoken briefs; no Grok login or
subscription token is copied onto Coolify.

Validation includes the MCP initialize/list/call HTTP exchange, bearer rejection,
revocation, forbidden approval access, durable replay, spacing, isolated revisions,
and blog creation through the existing review path (`test_agent.py`). A successful
server test is not a completed connection to the user's Grok Bot account: the
owner must add the secret header in Grok Bot and call get_editorial_context.


### Optional article authorized with a social post

The owner review card exposes **Créer aussi un article de blog**, unchecked by
default, or preselected when the Bot requested it in the brief. Submitting owner approval with `create_blog: true` atomically approves
the social revision and records a one-to-one article grant. The owner session API or the explicitly authorized Grok approval relay can grant
it. Preparing or scheduling a draft with create_blog only requests the option;
it does not grant approval.
A dedicated durable job drafts and illustrates the article using the approved
social text, sources, frozen product and owner photo references. It then seals
the generated article for publication without a second owner review. The article
is published as soon as its text and illustrations are ready, even if the social
post is scheduled much later.
Ordinary standalone and weekly blog articles keep their separate review.

The parent revision/hash and child revision are checked before generation,
before sealing and in the final public-projection transaction. A changed or
unapproved parent prevents automatic publication. Reapproving with the option
unchecked revokes an unpublished companion; opting in again reuses the same
article rather than duplicating it. Already published articles remain intact.
Missing product references, media integrity or catalogue checks still block
publication. Resume handles both a finished draft and an interrupted render.

Articles and assets are stored in the studio's persistent SQLite/media volume.
The storefront reads `/editorial/public/articles` and renders published entries
on its own blog pages (feed cache approximately 60 seconds). There is no write
into Medusa. The weekly schedule and social calendar spacing are unchanged.
Tests in `test_companion.py` exercise delegation, revocation, recovery and public
projection using local fakes, with no live article or social publication.


### Owner approval relayed through Grok Bot

`prepare_content(create_blog=true, scheduled_at=...)` sets the proposed date and
companion article checkbox. `schedule_content` adjusts a ready, unapproved draft
without generating its text or visuals again; it checks social spacing and
increments the revision. Other items and weekly plans are preserved.

Grok must show both captions, the image from `get_visual`, the effective Paris
date and the article option, then wait for the owner's explicit agreement.
`approve_content` records the actual confirmation words and checks the exact
review token (content, image metadata, revision, date and article option) plus a
matching served visual. New edits require a new preview and agreement. Approval
and durable request replay are one SQLite transaction, including companion
creation. Duplicate retries cannot approve a second time or create two articles.
The regular publisher checks media bytes, commercial data and spacing before
actual delivery. Social posts enter Postiz's calendar; companion articles publish
as soon as ready. Owner session APIs and connector administration remain separate.

This is a trusted confirmation relay: the server verifies version/preview and
records the agent's confirmation assertion, but cannot independently verify that
the human spoke those words or saw the image in Grok. The connector's bearer key
therefore now carries the explicitly requested approval capability. The Bot's
instructions prohibit inventing consent or treating a creation brief as approval.


### Varied product-aware photographic direction

`scenes.py` requests three concrete compatible directions (setting, lighting,
angle, staging and product-fit explanation) from the text model before image
creation. The choice favors settings outside the latest two directions, then
less-used settings/combinations in the latest twelve, shared across social and
blog. Legacy scene briefs also inform the first choices. An explicitly requested
location can remain fixed while lighting and framing vary. This is direction
memory, not pixel-similarity detection or a claim of guaranteed visual diversity.

The selected `pl-scenes-v2` direction is durable per item/revision, survives
image retries, and is included in the final media/approval hash. Concurrent edits
reject a stale direction. The image prompt no longer imposes warm light, wood,
matte materials or green decor. The existing logo/type/layout charter remains
`pl-social-v1`; exact photo references and acknowledgment checks are unchanged.
The rules require product-appropriate contexts and reject implied unverified
uses (weather resistance, stage capacity, compatibility or supplied accessories).
No existing post is regenerated or approval changed during deployment.


### Blog length

Blog drafting targets at least 500 words and has no editorial upper word/character
limit. The Markdown editor has no maxlength. Blog briefs, rewrite instructions
and previous article bodies are passed through without editorial truncation;
Instagram platform limits still apply; display metadata is normalized. HTTP/model transport bounds
still protect resource usage and are distinct from an article-length rule.


### Non-blocking editorial review

Source omissions, model uncertainty, commercial mentions and drafts below the
500-word writing target are retained as private `content.editorial_notes`, visible
to Grok and in the review screen. They never fail a draft or create a second
approval requirement. The writer must omit unsupported facts rather than invent
them. Display metadata is shortened automatically; slugs and categories are
normalized. Article bodies are never truncated. Invalid payloads, unsafe markup
and links, platform limits, product reference integrity, explicit consent,
revision sealing, scheduling spacing and duplicate-delivery protections remain.
The public blog projection excludes these private notes.
