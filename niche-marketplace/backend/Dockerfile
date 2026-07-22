# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps: libpq for psycopg, plus build essentials for any wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for better layer caching. Dev image includes
# lint/test tooling; prod builds can target requirements.txt instead.
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

COPY . .

EXPOSE 8000

# Default command is overridden by docker-compose for dev (runserver).
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
