# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Full-stack single image: builds the React SPA, then serves it + the API from
# one FastAPI/uvicorn process. Result: one URL (http://localhost:8000) hosting
# both the ISN dashboard and the shopper landing page — ideal for attribution.
# ---------------------------------------------------------------------------

# ---------- Stage 1: build the frontend ----------
FROM node:20-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# ---------- Stage 2: backend runtime ----------
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
# Drop the built SPA where FastAPI's StaticFiles/catch-all serves it (STATIC_DIR=static).
COPY --from=frontend /frontend/dist ./static

EXPOSE 8000
# Schema creation + demo seeding happen automatically on startup (lifespan).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
