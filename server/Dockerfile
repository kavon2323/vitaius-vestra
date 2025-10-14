# ---- Base: FastAPI server ----
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy minimal requirements first for better caching
COPY server/requirements.txt /app/server/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/server/requirements.txt

# Copy app code
COPY . /app

EXPOSE 8000

# Uvicorn hot-reload for dev (switch to gunicorn+uvicorn for prod)
CMD ["uvicorn", "server.api:app", "--host", "0.0.0.0", "--port", "8000"]
