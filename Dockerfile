# ── Frontend build stage ───────────────────────────────────────────────
FROM node:26-alpine AS frontend

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json* ./
# Build stage: install ALL deps (incl. devDependencies — esbuild/tailwind
# are required to build the static bundle). --only=production would skip
# them and fail with "esbuild binary not found for linux-x64".
RUN npm ci 2>/dev/null || npm install

COPY frontend/ ./
RUN npm run build

# ── Python runtime stage ───────────────────────────────────────────────
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY backend/ /app/
COPY scripts/ /app/scripts/

# Copy compiled frontend assets (no Node.js runtime)
COPY --from=frontend /build/static/ /app/static/

# Collect static files
RUN python manage.py collectstatic --noinput 2>/dev/null || true

# Create non-root user
RUN addgroup --system app && adduser --system --ingroup app app \
    && chown -R app:app /app

USER app

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

STOPSIGNAL SIGTERM
CMD ["gunicorn", "sentinel_review.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--threads", "2", "--timeout", "60"]
