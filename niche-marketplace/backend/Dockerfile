# syntax=docker/dockerfile:1
#
# Two targets:
#   dev  — adds ruff/pytest tooling; used by docker-compose.yml (build target: dev)
#   prod — runtime deps only; this is what CI publishes to GHCR (default target)

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps: libpq for psycopg, plus build essentials for any wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for better layer caching.
COPY requirements.txt ./
RUN pip install -r requirements.txt

EXPOSE 8000

# Overridden by compose (runserver in dev, gunicorn/celery in prod).
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]


# --- dev: lint/test tooling on top of the runtime deps ----------------------
FROM base AS dev

COPY requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

COPY . .


# --- prod: runtime only, no lint/test tooling shipped to the box ------------
# Last stage, so a plain `docker build` produces the production image.
FROM base AS prod

COPY . .
