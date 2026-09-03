"""FastAPI application entrypoint.

Serves, from a single origin:
  * the JSON API under ``/api/*``
  * the public tracking endpoints (``/r/{token}``, ``/track/open/{token}.gif``)
  * the built React SPA (everything else), so both the ISN dashboard and the
    shopper landing page share one URL/host — which keeps token-based
    attribution simple and same-origin.
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import __version__
from .config import settings
from .database import AsyncSessionLocal, init_models
from .routers import (
    ai,
    admin_users,
    auth,
    automations,
    campaigns,
    client_portal,
    dashboard,
    email_templates,
    integrations,
    invitations,
    misc,
    notifications,
    recommendations,
    reports,
    shoppers,
    shops,
    social,
    tracking,
    voice,
    voice_calls,
    webhooks,
)
from .seed import maybe_seed
from .services.automation import ensure_default_templates, run_automation_scheduler
from .services.outbox import reset_stuck_jobs, run_outbox_worker
from .services.social_publisher import run_social_publisher
from .services.voice_call_scheduler import run_voice_call_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    if "localhost" in settings.public_base_url.lower():
        print("WARNING: PUBLIC_BASE_URL contains localhost. Tracking links and open pixels will not work for external recipients until you set it to a public URL (for example, an ngrok https forwarding URL).")
    await init_models()
    if settings.auto_seed:
        seeded = await maybe_seed()
        if seeded:
            print("✅ Seeded demo data (database was empty).")
    requeued = await reset_stuck_jobs()
    if requeued:
        print(f"Requeued {requeued} email job(s) stuck in 'sending' from a previous run.")
    async with AsyncSessionLocal() as session:
        await ensure_default_templates(session)
        await session.commit()
    worker = asyncio.create_task(run_outbox_worker(), name="shoppermatch-email-outbox")
    automation_worker = asyncio.create_task(run_automation_scheduler(), name="shoppermatch-automation-scheduler")
    social_worker = asyncio.create_task(run_social_publisher(), name="shoppermatch-social-publisher")
    voice_call_worker = asyncio.create_task(run_voice_call_scheduler(), name="shoppermatch-voice-call-followup")
    try:
        yield
    finally:
        worker.cancel()
        automation_worker.cancel()
        social_worker.cancel()
        voice_call_worker.cancel()
        for task in (worker, automation_worker, social_worker, voice_call_worker):
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title=f"{settings.app_name} API",
    description=(
        "Intelligent Shopper Outreach & Attribution Platform.\n\n"
        "Demonstrates end-to-end outreach attribution: ISN email → unique UUID "
        "token → tracking pixel → FastAPI → PostgreSQL → click tracking → shopper "
        "landing page → accept/decline → ISN dashboard."
    ),
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    # Auth uses bearer tokens (Authorization header), not cookies, so we keep
    # credentials off — this makes a wildcard origin safe and simple.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------ API routers ------------------------------ #
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(campaigns.router)
app.include_router(shoppers.router)
app.include_router(shops.router)
app.include_router(recommendations.router)
app.include_router(invitations.router)
app.include_router(tracking.router)  # public /r, /track + /api/tracking/*
app.include_router(email_templates.router)
app.include_router(webhooks.router)  # public /api/webhooks/sendgrid
app.include_router(notifications.router)
app.include_router(integrations.router)
app.include_router(ai.router)
app.include_router(client_portal.router)
app.include_router(automations.router)
app.include_router(reports.router)
app.include_router(admin_users.router)
app.include_router(misc.router)
app.include_router(voice.router)
app.include_router(social.router)
app.include_router(voice_calls.router)


@app.get("/api/health", tags=["Meta"])
async def health():
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": __version__,
        "database": "sqlite" if settings.is_sqlite else "postgresql",
        "email_provider": settings.email_provider,
    }


@app.get("/api", tags=["Meta"])
async def api_root():
    return {
        "name": f"{settings.app_name} API",
        "version": __version__,
        "docs": "/docs",
        "public_base_url": settings.public_base_url,
    }


# ------------------------------ SPA serving ------------------------------ #
STATIC_DIR = os.path.abspath(settings.static_dir)
INDEX_HTML = os.path.join(STATIC_DIR, "index.html")

_RESERVED_PREFIXES = ("api", "r/", "track/", "docs", "redoc", "openapi.json")

_FALLBACK_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>ShopperMatch.AI — backend running</title>
<style>body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#0f172a;color:#e2e8f0;
max-width:720px;margin:8vh auto;padding:0 24px;line-height:1.6}a{color:#818cf8}code{background:#1e293b;
padding:2px 6px;border-radius:6px}</style></head><body>
<h1>ShopperMatch<span style="color:#6366f1">.AI</span> backend is running ✅</h1>
<p>The API is live but no built frontend was found in <code>%s</code>.</p>
<ul>
<li>Interactive API docs: <a href="/docs">/docs</a></li>
<li>Health: <a href="/api/health">/api/health</a></li>
</ul>
<p>For the full UI, either run the Vite dev server (<code>cd frontend &amp;&amp; npm run dev</code>)
or build it (<code>npm run build</code>) so this backend can serve it.</p>
</body></html>""" % STATIC_DIR


@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str, request: Request):
    # Never hijack API / tracking / docs routes.
    if full_path.startswith(_RESERVED_PREFIXES):
        return JSONResponse({"detail": "Not found"}, status_code=404)

    # Serve real static assets (JS/CSS/images/favicon) if present, safely.
    if full_path:
        candidate = os.path.normpath(os.path.join(STATIC_DIR, full_path))
        if candidate.startswith(STATIC_DIR + os.sep) and os.path.isfile(candidate):
            return FileResponse(candidate)

    # Otherwise return the SPA shell (client-side routing) or a fallback page.
    if os.path.isfile(INDEX_HTML):
        return FileResponse(INDEX_HTML)
    return HTMLResponse(_FALLBACK_PAGE)
