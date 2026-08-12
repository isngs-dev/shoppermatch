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
