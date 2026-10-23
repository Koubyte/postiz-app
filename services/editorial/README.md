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
projections. Draft/source/mask media require the owner's session. Only the actual
published article cover is available from `/editorial/public/media/...`.
The storefront merges this feed with its two historical guides. Social posts do
not automatically link an unpublished article; they are useful standalone
adaptations. Statistics-driven topic optimization is not part of this version.

Product photography is preserved as a protected RGB layer. Existing transparency
or the pinned U2netp model through direct ONNXRuntime CPU inference is used;
ambiguous masks and supplier image restrictions block output. The model is
provisioned and SHA-256 checked at image build and checked again before loading.
A conservative white-background fallback applies only without a model. Nothing
is downloaded implicitly at runtime. The
owner reviews the source and composition before approving media rights/fidelity.
A product whose photo cannot be safely composed remains blocked, never replaced
by a fictitious product. Backgrounds use the existing Codex OAuth image bridge.

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
