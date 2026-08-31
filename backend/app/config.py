"""Application configuration.

All configuration is sourced from environment variables (12-factor style).
A `.env` file is loaded automatically in development. See `.env.example`.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Always resolve the root .env relative to this source file, so the
        # documented project-root .env works whether uvicorn starts in backend/
        # (local script) or in the Docker image.
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ----- General -----
    app_name: str = "ShopperMatch.AI"
    app_tagline: str = "AI-powered shopper recruitment, outreach & attribution"
    environment: str = "development"  # development | production

    # Secret used to sign session/access tokens. MUST be overridden in production.
    secret_key: str = "dev-insecure-secret-change-me-in-production"

    # ----- Database -----
    # Postgres (production / docker):
    #   postgresql+asyncpg://shoppermatch:shoppermatch@db:5432/shoppermatch
    # SQLite fallback (zero-dependency local dev), used by default:
    #   sqlite+aiosqlite:///./shoppermatch.db
    database_url: str = "sqlite+aiosqlite:///./shoppermatch.db"

    # ----- Public URLs -----
    # Public origin the app is reachable at. Used to build the tracking pixel,
    # click-tracking and shopper-landing URLs that get embedded in emails.
    public_base_url: str = "http://localhost:8000"
    # Optional approved external destination for the invitation CTA. The click
    # is recorded by /r/{token} before the browser is redirected there.
    invitation_destination_url: str | None = None

    # ----- CORS -----
    # Comma-separated list of allowed origins, or "*" for all (demo default).
    cors_origins: str = "*"

    # ----- Email -----
    email_provider: str = "mock"  # mock | sendgrid | smtp | direct | emailjs
    sendgrid_api_key: str | None = None
    # Optional: SendGrid Event Webhook "Verification Key" (Settings → Mail Settings
    # → Event Webhook → Signed Event Webhook Requests). When set, incoming
    # /api/webhooks/sendgrid requests are ECDSA-signature-verified; when unset,
    # the webhook still works but accepts unverified requests (fine for a demo
    # behind a private ngrok URL, not for production).
    sendgrid_webhook_verification_key: str | None = None
    # EmailJS (emailjs.com) — typically routes through Gmail via OAuth rather than
    # raw SMTP AUTH, so it isn't subject to Google's "unauthorized app password
    # login" blocks. Service/Template come from the EmailJS dashboard; Private Key
    # authorizes server-side (non-browser) calls.
    emailjs_service_id: str | None = None
    emailjs_template_id: str | None = None
    emailjs_public_key: str | None = None
    emailjs_private_key: str | None = None
    email_from_name: str = "ISN Shopper Recruitment"
    email_from_address: str = "recruitment@isn-demo.example"
    # Gmail STARTTLS defaults. For Gmail, EMAIL_FROM_ADDRESS must exactly match SMTP_USERNAME.
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None

    # ----- Internal email outbox -----
    # ShopperMatch owns the queue/retry history; the selected provider is only
    # the final transport that accepts the rendered message.
    email_worker_poll_seconds: float = 3.0
    email_max_attempts: int = 3

    # ----- Bulk email throttling -----
    # Global governor applied to every send that flows through the outbox
    # (manual sends, automation sequences, everything) — not a per-source
    # limit. Once `bulk_email_batch_size` sends land in a row, the worker
    # pauses for `bulk_email_batch_delay_seconds` before continuing; once
    # `bulk_email_daily_limit` sends have completed in a rolling 24h window,
    # the worker stops claiming new jobs until the window rolls forward.
    bulk_email_batch_size: int = 1000
    bulk_email_daily_limit: int = 5000
    bulk_email_batch_delay_seconds: float = 300.0

    # ----- Email automation engine -----
    # How often the background scheduler checks for due automation steps.
    # Independent of email_worker_poll_seconds — the outbox still delivers
    # each individual message quickly; this only controls how often the
    # sequencing engine looks for shoppers whose wait period has elapsed.
    automation_poll_seconds: float = 30.0

    # ----- Auth -----
    demo_admin_name: str = "ISN Admin"
    demo_admin_email: str = "admin@isn.com"
    demo_admin_password: str = "isn-demo-2026"
    access_token_expire_minutes: int = 720  # 12 hours

    # ----- Static frontend -----
    # Directory containing the built React SPA (index.html + assets/). When it
    # exists the backend serves the full app from a single origin; otherwise a
    # helpful fallback page is shown (use the Vite dev server in that case).
    static_dir: str = "static"

    # ----- Seeding -----
    auto_seed: bool = True  # seed demo data on startup if the DB is empty

    # ----- Rate limiting (tracking endpoints) -----
    tracking_rate_limit_per_minute: int = 240

    # ----- Demo mode -----
    # When true (default for this project), integrations without real
    # credentials configured run on their demo/mock adapter instead of
    # reporting DISCONNECTED — the app stays demonstrable end-to-end. The UI
    # always labels this DEMO, never CONNECTED, so it's never confused with
    # a real external connection.
    demo_mode: bool = True

    # ----- Integrations: SASSIE -----
    sassie_api_base_url: str | None = None
    sassie_api_key: str | None = None
    sassie_client_id: str | None = None

    # ----- Integrations: Google Maps -----
    google_maps_api_key: str | None = None

    # ----- Integrations: AI -----
    # This project's recommendation engine (services/semantic_matching.py) is
    # a local rule-based + TF-cosine engine — it does not call any of these.
    # They exist so a future external provider swap is just a config change.
    ai_provider: str | None = None
    ai_model: str | None = None
    ai_api_key: str | None = None

    # ----- Integrations: SMS -----
    sms_provider: str | None = None
    sms_api_key: str | None = None
    sms_sender: str | None = None

    # ----- Voice Assistant (client portal "Hey" wake-word assistant) -----
    # Real OpenAI calls (Whisper transcription, GPT tool-calling, TTS) — unlike
    # `ai_api_key` above, this one is actually wired up and used.
    openai_api_key: str | None = None
    openai_chat_model: str = "gpt-4o-mini"
    openai_whisper_model: str = "whisper-1"
    openai_tts_model: str = "tts-1"
    openai_tts_voice: str = "alloy"
    # Used by Region-Targeted Social Media Posting to generate the post
    # graphic — same key as everything else above, one more OpenAI capability.
    openai_image_model: str = "gpt-image-1"

    @property
    def resolved_database_url(self) -> str:
        # Managed Postgres add-ons (Railway, Render, Heroku, ...) inject a
        # plain `postgresql://` or `postgres://` DATABASE_URL — SQLAlchemy's
        # async engine needs the asyncpg driver named explicitly in the
        # scheme. Local dev/sqlite and an already-qualified URL pass through
        # unchanged.
        url = self.database_url
        if url.startswith("postgres://"):
            return "postgresql+asyncpg://" + url[len("postgres://") :]
        if url.startswith("postgresql://"):
            return "postgresql+asyncpg://" + url[len("postgresql://") :]
        return url

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def cors_origin_list(self) -> list[str]:
        raw = (self.cors_origins or "").strip()
        if raw in ("", "*"):
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
