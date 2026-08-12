# ShopperMatch.AI — Intelligent Shopper Outreach & Attribution Platform

> AI-powered shopper recruitment, outreach & attribution for mystery shopping operations.

A **real, working end-to-end demo** (not a mockup) that shows how ISN can send a shopper
invitation by email and then see exactly **which shopper interacted with it** — through a
UUID tracking token, an email-open pixel, a click-tracking redirect, and a live dashboard.

```
ISN Email → Unique UUID → Tracking Pixel → FastAPI → PostgreSQL
          → Click Tracking → Shopper Landing Page → Accept/Decline → ISN Dashboard
```

---

## The two URLs to demonstrate

Everything is served from **one origin** (default `http://localhost:8000`):

| Side | URL | What it shows |
|------|-----|---------------|
| **ISN / company** | `http://localhost:8000/dashboard` → **Tracking** page | Sent → Delivered → Opened → Clicked → Accepted, per-shopper timelines, "✓ ISN ATTRIBUTED" |
| **Shopper / client** | `http://localhost:8000/shop/{tracking_token}` | The invitation landing page. Reaching it via the ISN link records the interaction against the ISN invitation. |

Example generated links (the token is created at runtime in **Outreach → Generate Invitation**):

- Tracking (click) URL: `http://localhost:8000/r/8f3c9d51-7d6e-4a19-9a2c-123456789abc`
- Email open pixel: `http://localhost:8000/track/open/8f3c9d51-7d6e-4a19-9a2c-123456789abc.gif`
- Shopper landing: `http://localhost:8000/shop/8f3c9d51-7d6e-4a19-9a2c-123456789abc`

**Demo admin login:** `admin@isn.com` / `isn-demo-2026`

---

## Quick start

### Option A — Docker (recommended, one command)

Requires Docker Desktop. Brings up PostgreSQL + the full-stack app, auto-creates the schema
and seeds demo data.

```bash
docker compose up --build
```

Then open **http://localhost:8000**. Sign in with the demo credentials above.

### Option B — Local, no Docker (SQLite, zero external services)

Requires **Python 3.11+** and **Node 18+**.

**Backend** (terminal 1):
```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    |    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# So generated tracking/pixel/shopper links point at the Vite dev server
# (which proxies /r and /track to this backend and serves /shop):
# Windows PowerShell:  $env:PUBLIC_BASE_URL="http://localhost:5173"
# macOS/Linux:         export PUBLIC_BASE_URL=http://localhost:5173
python -m app.seed          # creates SQLite DB + demo data
uvicorn app.main:app --reload --port 8000
```

**Frontend** (terminal 2):
```bash
cd frontend
npm install
npm run dev                 # http://localhost:5173 (proxies /api, /r, /track to :8000)
```

On Windows you can instead run the helper scripts:
```powershell
./scripts/run-backend.ps1     # sets up venv, seeds, runs the API
./scripts/run-frontend.ps1    # runs the Vite dev server
```

> In local dev the UI is at **http://localhost:5173**; the API + tracking endpoints are on
> **http://localhost:8000**. In Docker (or after `npm run build`) everything is on **:8000**.

---

## Architecture

```
                         ┌──────────────────────────────────────────────┐
                         │                Browser (SPA)                 │
                         │   React + TS + Tailwind + Recharts            │
                         │   /dashboard  /tracking  /outreach  /shop/:t  │
                         └───────────────┬──────────────────────────────┘
                                         │ same-origin /api, /r, /track
                         ┌───────────────▼──────────────────────────────┐
                         │                 FastAPI (async)              │
                         │  auth · dashboard · campaigns · shoppers     │
                         │  invitations · recommendations · tracking    │
                         │  /r/{token}  /track/open/{token}.gif         │
                         └───────────────┬──────────────────────────────┘
                                         │ SQLAlchemy 2.x async (asyncpg)
                         ┌───────────────▼──────────────────────────────┐
                         │   PostgreSQL  (SQLite fallback for local)    │
                         │  users shoppers campaigns shops              │
                         │  invitations  invitation_events  audit_logs  │
                         └──────────────────────────────────────────────┘
```

The backend serves the built SPA itself, so the ISN dashboard and the shopper landing page
share one host — which keeps token-based attribution simple and same-origin.

### Project structure

```
demo tracker/
├── Dockerfile                 # full-stack single image (SPA + API)
├── docker-compose.yml         # db + app
├── .env.example               # compose overrides
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app, CORS, SPA serving, lifespan (init+seed)
│   │   ├── config.py          # env-driven settings
│   │   ├── database.py        # async engine/session (Postgres or SQLite)
│   │   ├── models.py          # SQLAlchemy 2.x ORM (UUID PKs, JSONB events)
│   │   ├── schemas.py         # Pydantic request/response models
│   │   ├── serializers.py     # JSON-safe payloads, token masking, URL builders
│   │   ├── security.py        # PBKDF2 hashing + HMAC access tokens (stdlib only)
│   │   ├── rate_limit.py       # in-memory sliding-window limiter
│   │   ├── deps.py            # auth dependency
│   │   ├── seed.py            # demo data (10 shoppers, 3 campaigns, 8 shops, 24 invites)
│   │   ├── routers/           # auth, dashboard, campaigns, shoppers, shops,
│   │   │                      # recommendations, invitations, tracking, misc
│   │   └── services/          # tracking, email (mock+sendgrid), recommendation,
│   │                          # analytics, insights, audit
│   ├── alembic/               # async migrations (baseline 0001_initial)
│   ├── tests/test_acceptance.py  # section-29 end-to-end test
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    ├── src/pages/             # Home, Login, Dashboard, Tracking, Outreach, ShopperInvite, …
    ├── src/components/        # Layout, Timeline, Funnel, Attribution, InvitationDrawer, …
    ├── src/lib/               # api client, auth, theme, formatters
    └── package.json
```

---

## Tech stack

- **Frontend:** React 18, TypeScript, Tailwind CSS 3, Recharts, React Router, Vite.
- **Backend:** Python, FastAPI, async endpoints, SQLAlchemy 2.x (async), asyncpg, Pydantic v2, Alembic.
- **Database:** PostgreSQL (async via asyncpg). SQLite (aiosqlite) fallback for zero-dependency local runs.
- **Email:** Mock provider (default) with a preview UI; optional SendGrid adapter via env vars.
- **No hard dependency** on Redis/Celery/Neo4j — the architecture is structured so they can be added later.

---

## Database schema

All primary keys are **UUIDs** (no raw integer ids in public URLs). Timestamps are UTC.

- **users** — `id, name, email, role, password_hash, created_at`
- **shoppers** — `id, shopper_code, name, email, phone, city, state, zip_code, latitude, longitude,
  categories(JSON), availability_status, source, rating, completion_rate, previous_assignments, active, created_at`
- **campaigns** — `id, name, client_name, description, status, total_shops, completed_shops, remaining_shops, created_at, deadline`
- **shops** — `id, campaign_id, shop_name, address, city, state, latitude, longitude, required_shoppers,
  compensation, currency, category, visit_start, visit_end, status`
- **invitations** — `id, campaign_id, shop_id, shopper_id, tracking_token(UUID, unique), reference, email,
  subject, status, sent_at, delivered_at, opened_at, clicked_at, responded_at, response, source,
  utm_source, utm_medium, utm_campaign, utm_content, created_at`
- **invitation_events** — `id, invitation_id, event_type, event_timestamp, metadata(JSONB)`
- **audit_logs** — `id, actor, action, entity_type, entity_id, summary, created_at, meta(JSONB)`

**Invitation status:** `created → sent → delivered → opened → clicked → accepted | declined`
**Event types:** `invitation_created, email_sent, email_delivered, email_opened, link_clicked, assignment_accepted, assignment_declined`

Event metadata stores only safe demo info (source, campaign, page, referrer, coarse `user_agent_summary`, UTM).
**Raw IP addresses are never stored.**

---

## Environment variables

See `backend/.env.example` (backend) and `.env.example` (compose). Key ones:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./shoppermatch.db` | DB connection. Postgres: `postgresql+asyncpg://user:pass@host:5432/db` |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Origin used to build tracking/pixel/shopper URLs embedded in emails |
| `SECRET_KEY` | `dev-insecure-...` | Signs access tokens — **change in production** |
| `EMAIL_PROVIDER` | `mock` | `mock` or `sendgrid` |
| `SENDGRID_API_KEY` | _(empty)_ | Required only for real SendGrid delivery |
| `AUTO_SEED` | `true` | Seed demo data on startup if DB is empty |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `TRACKING_RATE_LIMIT_PER_MINUTE` | `240` | Per-client rate limit on tracking endpoints |
| `DEMO_ADMIN_EMAIL` / `DEMO_ADMIN_PASSWORD` | `admin@isn.com` / `isn-demo-2026` | Demo login |

---

## Migrations & seeding

The app calls `create_all` on startup so the schema always exists for the demo. For a
"proper" Postgres workflow, Alembic is included:

```bash
cd backend
alembic upgrade head                              # apply the baseline schema
alembic revision --autogenerate -m "my change"   # after editing models
```

Seeding:

```bash
python -m app.seed            # seed only if empty
python -m app.seed --force    # drop everything and reseed
```

---

## API documentation

Interactive docs (OpenAPI/Swagger) are available at **`/docs`** and ReDoc at **`/redoc`**.

**Auth**
- `POST /api/auth/login` → `{ access_token, token_type, expires_in, user }`
- `GET  /api/auth/me`

**Dashboard & analytics**
- `GET /api/dashboard/metrics`
- `GET /api/tracking/summary` — KPI counts + rates + funnel
- `GET /api/tracking/events?invitation_id=&event_type=&limit=`

**Campaigns / shops / shoppers**
- `GET /api/campaigns`, `GET /api/campaigns/{id}`
- `GET /api/shops?campaign_id=`, `GET /api/shops/{id}`, `GET /api/shops/{id}/recommendations`
- `GET /api/shoppers?q=&availability=`, `GET /api/shoppers/{id}`
- `GET /api/recommendations?shop_id=&limit=`

**Invitations**
- `POST /api/invitations` — generate token + URLs, optionally send email
- `GET  /api/invitations`, `GET /api/invitations/{id}`
- `GET  /api/invitations/{id}/email?preview=1` — rendered email (non-firing pixel when preview)
- `POST /api/invitations/{id}/simulate` — demo helper `{action: open|click|accept|…}` (writes real events)

**Public tracking (no auth)**
- `GET  /r/{tracking_token}` — records `link_clicked`, 302-redirects to `/shop/{token}`
- `GET  /track/open/{tracking_token}.gif` — records `email_opened`, returns a 1×1 GIF
- `GET  /api/public/invitations/{tracking_token}` — landing-page data
- `POST /api/invitations/{tracking_token}/respond` — `{ response: "accepted" | "declined" }`

**Admin extras**
- `GET /api/audit-logs`, `GET /api/insights`, `GET /api/integrations`, `GET /api/settings`, `GET /api/health`

---

## Tracking architecture

Every invitation gets a **unique, unguessable UUID `tracking_token`** that maps to exactly one
invitation. Public URLs use only that token — **no internal database ids are ever exposed**.

### Click tracking — `GET /r/{tracking_token}`
1. Validate token → find invitation.
2. Record a `link_clicked` event (with UTM + coarse UA summary) and set `clicked_at`.
3. Advance status to `clicked` (status only ever moves forward).
4. **302 redirect** to the first-party `/shop/{token}` landing page (safe redirect — never to an external URL).

### Email-open pixel — `GET /track/open/{tracking_token}.gif`
1. Validate token → find invitation.
2. Record an `email_opened` event **once** (deduplicated) and set `opened_at`.
3. Return a real **1×1 transparent GIF** with `Content-Type: image/gif` and anti-cache headers.

The email HTML embeds it with no JavaScript required:
```html
<img src="https://YOUR_DOMAIN/track/open/{tracking_token}.gif"
     width="1" height="1" style="display:block;border:0;" alt="" />
```

### Why email-open tracking is **approximate**, and click tracking is more **reliable**
- **Opens** rely on the recipient's email client actually loading remote images. Many clients
  **block, proxy, or pre-fetch** images (e.g. Apple Mail Privacy Protection, Gmail's image proxy).
  That means an "open" can be **missed** (images blocked) or **over-counted / early** (proxy prefetch).
  So we present "Opened" as an **approximate signal**, not proof a human read the email.
- **Clicks** require a deliberate user action (following the `/r/{token}` link). They are far
  harder to trigger accidentally and are recorded server-side, so click + response are the
  **reliable, high-confidence** attribution signals.

### How UUID-based attribution works
Because the token is unique per invitation, any hit on `/r/{token}`, `/track/open/{token}.gif`,
or a response on `/shop/{token}` is unambiguously tied back to that one invitation — and therefore
to its **campaign, shop, shopper, source (ISN) and UTM parameters**. The dashboard surfaces this as
a per-shopper timeline and a **"✓ ISN ATTRIBUTED"** badge.

---

## Demo workflow (live script)

1. Open **http://localhost:8000**, click **Open ISN Dashboard**, sign in (`admin@isn.com` / `isn-demo-2026`).
2. Note the **Tracking** page baseline numbers (Sent / Delivered / Opened / Clicked / Accepted).
3. Go to **Outreach**. Campaign = *Nike Mumbai Store Audit*, shopper = **Sarah Johnson** (pre-selected).
4. Click **Generate Invitation** → a unique tracking token, three URLs and an email preview appear.
5. Click **Preview Email** to show the real invitation (the "View Assignment" button uses the tracking URL).
6. Click **Simulate Email Open** → the event is written to the DB; the timeline gains *Email Opened*.
   Refresh **Tracking** → **Opened** increments.
7. Click **Open Tracking Link** (or, in a real client, the email button). The browser hits
   `/r/{token}` → FastAPI records `link_clicked` → you're redirected to `/shop/{token}`.
8. On the shopper page, click **Accept Assignment**. FastAPI records the response.
9. Back on the **Tracking** page, the row now shows **Clicked ✓** and **Accepted**, and clicking the
   row opens the full **event timeline** with timestamps and the **ISN ATTRIBUTED** badge.
10. Refresh the page (or open in a fresh browser) — all state is persisted in the database.

> The **Simulate** buttons and the real `/r` + pixel endpoints both write **real events** to the
> database. Nothing is faked in the frontend.

---

## Acceptance test

The exact section-29 flow is scripted and runs in-process (no server needed):

```bash
cd backend
pip install -r requirements.txt
pytest                     # or: ./scripts/run-acceptance-tests.ps1
```

It verifies: invitation creation + UUID token, click event + timestamp, campaign/shopper
association, `source = ISN`, the 302 redirect, dashboard update, accept flow + `assignment_accepted`
event, the email-open pixel recording `email_opened`, and that state survives a fresh session.

---

## Security considerations

- **UUID tracking tokens**, validated server-side; **no raw DB ids** in public URLs.
- Admin API behind **bearer-token auth**; passwords hashed with **PBKDF2-HMAC-SHA256** (salted).
- **Rate limiting** on public tracking endpoints (sliding window per client).
- **Safe redirects** — `/r/{token}` only ever redirects to the first-party `/shop/{token}`.
- **Input validation** via Pydantic; **SQL-injection-safe** via SQLAlchemy parameterisation.
- **CORS** configurable; bearer-token auth means no cookies (wildcard origin stays safe).
- **Basic audit logging** of admin actions (`audit_logs`).
- **Privacy-preserving:** no raw IPs, no covert fingerprinting; only a coarse `user_agent_summary`.
- All data is **synthetic**. Secrets come from env vars; `.env.example` files are provided and no
  secrets are hardcoded.

---

## Deployment

- **Single full-stack image** (recommended): the root `Dockerfile` builds the SPA and serves it +
  the API from one uvicorn process. `docker compose up --build` also starts PostgreSQL.
- **Separate services:** `backend/Dockerfile` (API only) and `frontend/Dockerfile` + `frontend/nginx.conf`
  (SPA on nginx, proxying `/api`, `/r`, `/track` to the backend).
- **Production start command:** `uvicorn app.main:app --host 0.0.0.0 --port 8000` (add `--workers N`
  behind a process manager; keep `AUTO_SEED=false` and run migrations/seed explicitly for real deployments).
- Set `PUBLIC_BASE_URL` to your public origin so emailed tracking/pixel/shopper URLs resolve correctly.

---

## Deliverables reference

| Item | Value |
|------|-------|
| Frontend URL | `http://localhost:8000` (dev: `http://localhost:5173`) |
| Backend API URL | `http://localhost:8000/api` (docs at `/docs`) |
| ISN / Admin dashboard | `http://localhost:8000/dashboard` → Tracking |
| Shopper invitation URL | `http://localhost:8000/shop/{tracking_token}` |
| Example tracking URL | `http://localhost:8000/r/{tracking_token}` |
| Example pixel URL | `http://localhost:8000/track/open/{tracking_token}.gif` |
| Demo login | `admin@isn.com` / `isn-demo-2026` |

> This is a demo built to run on your infrastructure. It ships ready to deploy (Docker/compose,
> Alembic, `.env.example`), but is not itself hosted at a public URL — run `docker compose up`
> (or the local scripts) to bring it up on the URLs above, then point `PUBLIC_BASE_URL` at your
> domain to make the tracking links externally shareable.
