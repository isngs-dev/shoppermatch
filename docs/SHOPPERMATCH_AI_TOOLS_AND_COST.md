# SHOPPERMATCH.AI — Tools, Services, API Keys & Cost Estimation ("Tab 5")

**Pricing caveat (read first):** my knowledge has a cutoff and this project's "today" is 2026-08-13 — provider pricing changes without notice. Every number below marked with ⚠️ is an approximation from general knowledge, **not a live lookup**, and must be verified against the provider's current official pricing page before it's used in a client quote. Where I have no reasonable confidence at all, I've written **"Pricing requires verification from official provider"** instead of guessing, per instruction.

---

## 1. What's actually configured today (verified from `backend/app/config.py`)

| Env var | Currently set in this environment? |
|---|---|
| `DATABASE_URL` | Defaults to local SQLite file — no hosting cost today |
| `EMAIL_PROVIDER` | Defaults to `mock` — no external email cost today |
| `SENDGRID_API_KEY` | Not set in this demo |
| `GOOGLE_MAPS_API_KEY` | Not set |
| `SASSIE_API_KEY` / `SASSIE_API_BASE_URL` | Not set — running on the built-in demo adapter |
| `AI_PROVIDER` / `AI_API_KEY` | Not set — **no external AI provider is called anywhere in this codebase** |
| `SMS_PROVIDER` / `SMS_API_KEY` | Not set — no SMS send code path exists |

**Bottom line: this demo currently runs at $0 external API cost.** Everything below is what production would add, tool by tool.

---

## 2. Tool-by-tool breakdown

### SendGrid (email delivery)
1. **Why needed:** outbound outreach email delivery in production (`EMAIL_PROVIDER=sendgrid`).
2. **Feature that uses it:** Outreach send, `services/email.py::_send_via_sendgrid`.
3. **Free tier:** SendGrid has historically offered a limited free/trial tier for low email volume. ⚠️ Confirm current free-tier email/day limit on sendgrid.com/pricing — this has changed multiple times.
4. **Paid tier needed for:** any real production sending volume beyond the free tier.
5. **Approximate pricing:** ⚠️ Entry paid plans have historically been in the low tens of USD/month for a few tens of thousands of emails. **Pricing requires verification from official provider** (sendgrid.com/pricing) for exact current tiers.
6. **Usage-based:** yes, tiered by monthly email volume.
7. **Mandatory:** only if real email delivery is required; the app runs fully functionally on `EMAIL_PROVIDER=mock` for demos.
8. **Free alternative:** the app also supports `smtp` (e.g. Gmail app password, free but low-volume and easily rate-limited) and `emailjs` (EmailJS free tier exists, low volume) as already-coded alternatives — no code change needed to switch, only env vars.
9. **Required for MVP:** no (mock is sufficient for demoing).
10. **Required for production:** yes, if real shoppers must receive real email.

### Google Gemini / OpenAI / Anthropic (external AI)
1. **Why needed:** not needed by this codebase today — flagged only because the brief asked for it to be evaluated.
2. **Feature that uses it:** **none.** Every AI feature in `services/ai/*.py` is local, deterministic Python (regex parsing, TF-cosine similarity, Bayesian smoothing, lexicon sentiment). Confirmed by reading every file in `backend/app/services/ai/`.
3. **Free tier:** each provider has historically offered some free/trial credit. ⚠️ Verify current terms directly — these change frequently and vary by provider (OpenAI, Google Gemini, Anthropic).
4. **Paid tier needed for:** only if a future upgrade path replaces the TF-cosine matching with real embeddings or adds generative summarization calls.
5. **Approximate pricing:** token-based, varies enormously by model tier. **Pricing requires verification from official provider** for all three (openai.com/pricing, ai.google.dev/pricing, anthropic.com/pricing) — do not quote a number without checking.
6. **Usage-based:** yes, per-token for all three.
7. **Mandatory:** no — the current AI layer has zero dependency on any of these.
8. **Free alternative:** yes — a locally-hosted open-weights embedding model (e.g. via sentence-transformers) would avoid per-token cost entirely if real embeddings are ever adopted.
9. **Required for MVP:** no.
10. **Required for production:** only if/when the product roadmap explicitly decides to upgrade matching quality beyond TF-cosine — not a current requirement.

### Google Maps
1. **Why needed:** live geocoding/distance/routing.
2. **Feature that uses it:** none currently — `haversine_km` (pure coordinate math) is what distance scoring actually uses; Maps config exists in Integrations but no live API call happens in the matching pipeline.
3. **Free tier:** Google Maps Platform has historically included a monthly free credit. ⚠️ Verify current amount at developers.google.com/maps/billing-and-pricing.
4. **Paid tier needed for:** production-scale geocoding/routing beyond the free credit.
5. **Approximate pricing:** per-request, tiered by API (Geocoding vs. Distance Matrix vs. Directions differ). **Pricing requires verification from official provider.**
6. **Usage-based:** yes.
7. **Mandatory:** no — coordinate-based distance already works without it, and shoppers/shops already store lat/lng.
8. **Free alternative:** the coordinate-math fallback already in use, or an open geocoding service (e.g. Nominatim/OpenStreetMap, rate-limited but free) if live geocoding of new addresses is ever needed.
9. **Required for MVP:** no.
10. **Required for production:** only if live traffic-aware routing/geocoding of new addresses becomes a real requirement.

### PostgreSQL hosting (Render / Railway / equivalent managed Postgres)
1. **Why needed:** the production datastore (docker-compose already provisions this; only hosting is missing).
2. **Feature that uses it:** everything — it's the single source of truth.
3. **Free tier:** most managed Postgres providers (Render, Railway, Supabase, Neon) have offered small free tiers historically. ⚠️ Free-tier limits (storage, always-on vs. sleep) change often — verify current terms per provider.
4. **Paid tier needed for:** any real production workload with persistence guarantees / backups.
5. **Approximate pricing:** ⚠️ entry managed-Postgres paid plans have historically started in the single-digit-to-low-tens of USD/month for small instances. **Pricing requires verification from official provider** for exact current numbers (render.com/pricing, railway.app/pricing).
6. **Usage-based:** partially — storage + compute tiers.
7. **Mandatory:** yes for any real deployment (SQLite is dev/demo-only, not concurrent-write-safe for production).
8. **Free alternative:** self-hosted Postgres on a small VM, or SQLite for genuinely single-writer low-volume use.
9. **Required for MVP:** no (SQLite is fine for a demo).
10. **Required for production:** yes.

### Render / Railway / Vercel (app hosting)
1. **Why needed:** hosting the FastAPI+React single Docker image (backend) and/or the SPA separately (frontend, if split).
2. **Feature that uses it:** the whole application.
3. **Free tier:** Render/Railway/Vercel have all historically offered free tiers for small workloads with sleep-on-idle behavior. ⚠️ Verify current limits per provider.
4. **Paid tier needed for:** always-on production hosting.
5. **Approximate pricing:** ⚠️ small paid web-service tiers have historically started around single-digit-to-low-tens of USD/month. **Pricing requires verification from official provider.**
6. **Usage-based:** partially (compute/bandwidth tiers).
7. **Mandatory:** yes, something must host the app for it to be reachable outside local dev.
8. **Free alternative:** the free tiers above, for demos/staging only.
9. **Required for MVP:** yes, at minimum a free-tier deployment for stakeholder access.
10. **Required for production:** yes, paid tier for reliability.

### Redis (background jobs)
1. **Why needed:** not currently needed — `services/outbox.py` already implements the email queue as an in-process asyncio background task, no Redis/Celery involved.
2. **Feature that uses it:** none today.
3. **Free tier:** most managed Redis providers offer a small free tier. ⚠️ Verify current terms if adopted.
4. **Approximate pricing:** **Pricing requires verification from official provider** if this becomes needed.
5. **Mandatory:** no.
6. **Required for MVP/production:** no — only if job volume outgrows a single-process in-memory queue.

### Sentry (monitoring)
1. **Why needed:** production error monitoring — not currently integrated anywhere in the codebase.
2. **Free tier:** Sentry has historically offered a free developer tier with limited event volume. ⚠️ Verify current limits.
3. **Approximate pricing:** **Pricing requires verification from official provider** (sentry.io/pricing).
4. **Mandatory:** no, recommended for production.
5. **Required for MVP:** no.
6. **Required for production:** recommended, not currently wired in.

### Vector database (pgvector / Pinecone / etc.)
1. **Why needed:** would only matter if real embeddings replace the current TF-cosine approach.
2. **Currently used:** no — no vector database or extension is installed or referenced anywhere in this codebase.
3. **Free alternative:** `pgvector` is a free, open-source Postgres extension — the cheapest path if this is ever adopted, since Postgres is already the target production database.
4. **Mandatory:** no.
5. **Required for MVP/production:** no, not at 60-shopper scale.

### Embedding provider (Sentence Transformers / OpenAI embeddings / etc.)
1. **Currently used:** no.
2. **Free alternative:** self-hosted `sentence-transformers` model (free, CPU-inference is fine at this record count) instead of a paid embedding API.
3. **Mandatory:** no.

### SMS provider (Twilio or equivalent)
1. **Why needed:** SMS outreach channel — mentioned in the roadmap, no send code path exists yet.
2. **Free tier:** most SMS providers offer trial credit, not an ongoing free tier (SMS has a real per-message carrier cost).
3. **Approximate pricing:** per-message, varies heavily by destination country. **Pricing requires verification from official provider** (e.g. twilio.com/pricing) — do not quote a number.
4. **Mandatory:** no.
5. **Required for MVP:** no. **Required for production:** only if SMS outreach is actually built and adopted.

### SASSIE (mystery-shopping data platform)
1. **Why needed:** the real upstream source of shopper/campaign data this project is designed to eventually sync from.
2. **Currently used:** demo adapter only (`services/integrations/sassie.py`) — operates against this project's own existing database, never a real SASSIE call.
3. **Pricing:** SASSIE is an enterprise mystery-shopping platform; **pricing requires verification directly from SASSIE / ISN's existing commercial relationship** — this is not a self-serve SaaS with a public price list.
4. **Mandatory:** only for real production data sync; the demo adapter satisfies every current AI feature without it.

### Neo4j
1. **Currently used:** not configured anywhere in this codebase.
2. **Free tier:** Neo4j has historically offered a free Community Edition (self-hosted) and a free tier of Neo4j Aura (managed). ⚠️ Verify current terms.
3. **Mandatory:** no — see Architecture doc §7 for why this wasn't built.

### Kafka
1. **Currently used:** not configured anywhere in this codebase.
2. **Free alternative:** self-hosted Kafka (free, OSS) or a managed offering (Confluent Cloud has historically had a free trial credit — verify current terms) if ever adopted.
3. **Mandatory:** no — see Architecture doc §7.

---

## 3. Monthly cost estimate by stage

| Cost category | Demo (current state) | Low-scale MVP (real email, small Postgres, small hosting) | Production (real volume, monitoring, all integrations live) |
|---|---|---|---|
| Infrastructure (app hosting) | $0 (local) | ⚠️ Free–low tens USD/mo (small managed hosting tier) | ⚠️ Tens–low hundreds USD/mo, scales with traffic |
| Database (Postgres) | $0 (SQLite file) | ⚠️ Free–low tens USD/mo (small managed instance) | ⚠️ Tens–hundreds USD/mo depending on size/backups |
| Email (SendGrid or equivalent) | $0 (mock provider) | ⚠️ Free–low tens USD/mo at low volume | ⚠️ Scales per email volume — verify current tiers |
| SMS | $0 (not implemented) | $0 (not implemented) | ⚠️ Per-message cost if built — verify provider pricing |
| AI token cost | $0 (no external AI calls exist) | $0 (still no external AI calls) | $0 unless the roadmap explicitly adopts an external embedding/LLM provider |
| Maps | $0 (not called) | $0 (not called) | ⚠️ Per-request if live geocoding is adopted — likely covered by free monthly credit at low volume |
| Monitoring (Sentry) | $0 (not integrated) | $0 (optional free tier if added) | ⚠️ Free–low tens USD/mo depending on event volume |
| **Total (rough order of magnitude)** | **$0/mo** | **⚠️ roughly free–$100/mo**, dominated by whichever paid tiers are switched on | **⚠️ Cannot be responsibly estimated without current, provider-confirmed numbers and expected volume (campaigns/month, emails/month, shoppers).** |

**I'm not going to put a single confident dollar figure on "production cost"** — it depends entirely on email volume, hosting tier, and whether SMS/Maps/AI-provider upgrades are adopted, none of which are fixed yet. The categories above are the right shape for a real quote once those volumes are known; the dollar ranges need re-verification against live pricing pages at quote time.

---

## 4. Technology stack table

| Technology | Purpose | Where used | Free/Paid | Required for MVP? | Production requirement? |
|---|---|---|---|---|---|
| React 18 | Frontend UI | `frontend/src` | Free (OSS) | ✅ | ✅ |
| TypeScript | Type-safe frontend | `frontend/src/**/*.tsx` | Free (OSS) | ✅ | ✅ |
| Tailwind CSS | Styling | `frontend/src` | Free (OSS) | ✅ | ✅ |
| Recharts | Dashboard charts | `Dashboard.tsx` | Free (OSS) | ✅ | ✅ |
| Vite | Frontend build tool | build pipeline | Free (OSS) | ✅ | ✅ |
| FastAPI | Backend API framework | `backend/app` | Free (OSS) | ✅ | ✅ |
| Python 3.12 | Backend runtime | `backend/.venv` | Free (OSS) | ✅ | ✅ |
| SQLAlchemy 2.0 (async) | ORM | `backend/app/models.py` | Free (OSS) | ✅ | ✅ |
| Alembic | Migrations | `backend/alembic` | Free (OSS) | ✅ | ✅ |
| SQLite (aiosqlite) | Dev/demo database | default `DATABASE_URL` | Free | ✅ (demo) | ❌ (Postgres recommended) |
| PostgreSQL (asyncpg) | Production database | `docker-compose.yml` | Free (self-host) / Paid (managed) | ❌ | ✅ |
| httpx | Outbound HTTP (SendGrid/EmailJS/SASSIE) | `services/email.py`, `services/integrations/sassie.py` | Free (OSS) | ✅ | ✅ |
| cryptography | Token signing / webhook signature verification | `services/security.py`, webhooks | Free (OSS) | ✅ | ✅ |
| SendGrid | Real email delivery | `services/email.py` | Free tier + paid tiers (⚠️ verify) | ❌ | ✅ (or an alternative provider) |
| Google Maps API | Geocoding (not currently called) | Integrations config only | Free credit + paid (⚠️ verify) | ❌ | Optional |
| pytest / pytest-asyncio / httpx (test) | Testing | `backend/tests` | Free (OSS) | Recommended | Recommended |
| Docker | Containerized deployment | `Dockerfile`, `docker-compose.yml` | Free (OSS) | ❌ | Recommended |
| No vector DB | — | not used | — | ❌ | ❌ (not needed at current scale) |
| No Redis/Celery | — | not used | — | ❌ | ❌ (not needed at current scale) |
| No external AI provider | — | not used | — | ❌ | ❌ (current AI layer is fully local) |

---

## 5. Environment Variables (Section 24)

Only variables actually read by `backend/app/config.py` — **no secret values are included below, only variable names and purpose.**

| Variable | Purpose | Required |
|---|---|---|
| `DATABASE_URL` | DB connection string (SQLite or Postgres) | Yes (has a working default) |
| `PUBLIC_BASE_URL` | Base URL used to build tracking/pixel links | Yes for correct tracking links |
| `INVITATION_DESTINATION_URL` | Optional external post-click redirect | No |
| `SECRET_KEY` | Signs access tokens — **must change in production** | Yes |
| `ENVIRONMENT` | `development` \| `production` | No (has default) |
| `CORS_ORIGINS` | Allowed origins | No (defaults to `*`) |
| `EMAIL_PROVIDER` | `mock` \| `sendgrid` \| `smtp` \| `direct` \| `emailjs` | No (defaults to `mock`) |
| `SENDGRID_API_KEY` | SendGrid auth | Only if `EMAIL_PROVIDER=sendgrid` |
| `SENDGRID_WEBHOOK_VERIFICATION_KEY` | Verifies inbound SendGrid webhook signatures | Recommended for production |
| `EMAILJS_SERVICE_ID` / `EMAILJS_TEMPLATE_ID` / `EMAILJS_PUBLIC_KEY` / `EMAILJS_PRIVATE_KEY` | EmailJS auth | Only if `EMAIL_PROVIDER=emailjs` |
| `EMAIL_FROM_NAME` / `EMAIL_FROM_ADDRESS` | Sender identity (also used as SMTP username for Gmail) | Yes |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` | SMTP auth | Only if `EMAIL_PROVIDER=smtp` |
| `EMAIL_WORKER_POLL_SECONDS` / `EMAIL_MAX_ATTEMPTS` | Outbox worker tuning | No (has defaults) |
| `DEMO_ADMIN_NAME` / `DEMO_ADMIN_EMAIL` / `DEMO_ADMIN_PASSWORD` | Seeded admin login | No (has defaults — **must be changed for any real deployment**) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Session length | No (has default) |
| `STATIC_DIR` | Built SPA location | No (has default) |
| `AUTO_SEED` | Seed demo data if DB empty | No (has default) |
| `TRACKING_RATE_LIMIT_PER_MINUTE` | Rate limit on tracking endpoints | No (has default) |
| `DEMO_MODE` | Whether unconfigured integrations run on their demo adapter instead of reporting disconnected | No (has default) |
| `SASSIE_API_BASE_URL` / `SASSIE_API_KEY` / `SASSIE_CLIENT_ID` | Real SASSIE credentials | Only for live SASSIE sync |
| `GOOGLE_MAPS_API_KEY` | Google Maps auth | Only if live geocoding is adopted |
| `AI_PROVIDER` / `AI_MODEL` / `AI_API_KEY` | Reserved for a future external AI provider swap | Not used by any current code path |
| `SMS_PROVIDER` / `SMS_API_KEY` / `SMS_SENDER` | Reserved for future SMS integration | Not used by any current code path |

No `.env` file's actual contents are reproduced anywhere in this documentation — only variable names, matching `.env.example`.
