<!-- audiences: admin -->
# Administrators: running and configuring the platform

## Overall architecture of the whole project: components, workers and services (system overview)
ShopperMatch.AI is one deployable service. A React single-page app (TypeScript, Tailwind, Vite) talks to a FastAPI backend over /api, and the same backend serves the built app and the public tracking endpoints (/r/{token} click redirect, /track/open/{token}.gif open pixel, the shopper invitation page). Data lives in PostgreSQL (SQLite locally) through async SQLAlchemy: users, clients, shoppers, campaigns, shops, invitations, invitation events, email jobs, bonuses, chat conversations, social posts, automations and audit logs. Routers cover auth, dashboard, campaigns, shops, shoppers, recommendations, invitations, tracking, automations, voice calls, social media, reports, integrations, the AI orchestrator, AI Autopilot and the chatbot. Services hold the logic: semantic matching, staffing rules, the assignment optimiser, AI Autopilot, the email outbox, tracking, email rendering, voice-call AI and the chatbot agent. Background workers started with the app: the email outbox worker (queues, retries, throttling), the email automation scheduler, the social publisher, the AI voice call scheduler, the chatbot follow-up worker and the AI Autopilot scheduler. External services: OpenAI (chat, voice, images), an email provider (SendGrid, SMTP or EmailJS), Plivo (voice calls), Meta (Facebook publishing) and SASSIE (source platform sync).

## How a request becomes an email that is tracked
Choosing shoppers creates invitation rows (status created). Sending queues an email job in the outbox; the outbox worker renders the email with the invitation's tracking token, sends it through the configured provider and records sent and delivered. The open pixel, the click redirect and the shopper page each write an invitation event and advance the invitation status. Everything is attributed to the one invitation, its campaign, shop and shopper, and audit logs record who triggered what.

## Running the platform locally
The backend is a FastAPI app and the frontend a React app built with Vite. Locally the API runs on port 8000 (uvicorn app.main:app) and the UI on port 5173, which proxies /api, /r and /track to the API. If another program already uses a port, start the API on a different one and tell Vite where it is with the API_TARGET environment variable. Docker Compose brings up PostgreSQL and the full app on one port.

## Environment variables that matter most
DATABASE_URL (SQLite locally, PostgreSQL in production), PUBLIC_BASE_URL (the public origin used in tracking links), SECRET_KEY (signs access tokens, change in production), EMAIL_PROVIDER (mock, sendgrid, smtp or emailjs) with SENDGRID_API_KEY or the SMTP and EmailJS settings, OPENAI_API_KEY (chat assistant, voice assistant, AI emails, image generation), PLIVO_AUTH_ID, PLIVO_AUTH_TOKEN and PLIVO_PHONE_NUMBER (AI voice calls), the Facebook app variables for social publishing, and the AUTOPILOT_* variables for AI Autopilot. Secrets are never shown in the UI and the assistant cannot change them.

## Switching on real email
Set EMAIL_PROVIDER to sendgrid (with a verified sender and API key), smtp (Gmail needs an app password and a matching From address) or emailjs, set PUBLIC_BASE_URL to the public address and restart. The Integrations page then shows the email connection status. Until then the mock provider only simulates delivery.

## AI Autopilot configuration
Autopilot settings can be set per campaign or as an account default in the UI. Environment defaults: AUTOPILOT_SCHEDULER (worker on or off), AUTOPILOT_POLL_SECONDS (5 minutes), AUTOPILOT_MIN_INTERVAL_MINUTES (30 per campaign), AUTOPILOT_DEFAULT_MODE (off), AUTOPILOT_MAX_RADIUS_KM (150), AUTOPILOT_MAX_BONUS_MULTIPLIER (2), AUTOPILOT_MIN_MATCH_SCORE (40), AUTOPILOT_MAX_INVITATIONS_PER_RUN (100), AUTOPILOT_FILL_EVERY_SHOP (true), AUTOPILOT_MAX_SHOPS_PER_SHOPPER (3) and AUTOPILOT_MAX_OPEN_PER_SHOPPER (5, across all campaigns). Set AUTOPILOT_SCHEDULER=false to stop the background worker entirely.

## Users, client activity and audit logs
Users lists client users and shoppers. Client Activity shows what client accounts have been doing. Audit Logs record significant actions (who, what, when) such as invitation creation, bulk sends, AI matching, approvals, bonus changes and AI Autopilot runs. These pages exist only in the Admin portal.

## Integrations and Settings
Integrations shows each connection (SASSIE, email provider, AI provider, Google Maps, SMS) with a status such as Connected, Demo, Disconnected, Configuration Required, Connection Failed, and lets you test a connection. In demo mode an integration without credentials runs on a demo adapter that is always labelled DEMO. Settings is a read-only view of the configuration. Secrets and settings cannot be changed through the assistant.

## Chat assistant administration
Admins can review chatbot conversations and escalations (shopper requests that need a coordinator) at the admin conversation endpoints or by asking the assistant for chat escalations. The staff assistant model can be changed with CHATBOT_STAFF_MODEL, the shopper assistant name and mode with CHATBOT_ASSISTANT_NAME and CHATBOT_MODE, and the coordinator reply promise with CHATBOT_COORDINATOR_SLA.

## Deployment
The root Dockerfile builds the SPA and serves it with the API from one uvicorn process. Render and Railway configuration files are included. Production should use PostgreSQL, set AUTO_SEED to false, change SECRET_KEY, set PUBLIC_BASE_URL, and add environment variables in the host's dashboard (render.yaml only applies on a Blueprint sync). New database columns are retrofitted automatically on startup.
