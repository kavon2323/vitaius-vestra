# ---- Base: FastAPI server ----
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# (optional, but handy for SSL/git)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git curl && \
    rm -rf /var/lib/apt/lists/*

# IMPORTANT: our build context is already /server on Render
WORKDIR /app

# Copy requirements from THIS folder (server/)
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

# Copy the rest of the app (api.py, etc.)
COPY . /app

# Expose a default (Render sets $PORT at runtime)
EXPOSE 8000

# Use Render's $PORT if present, otherwise 8000 locally
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}"]
