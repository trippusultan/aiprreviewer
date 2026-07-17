ARG SERVICE=gateway
# Set INSTALL_PROVIDERS=1 when building a service that calls the LLM layer
# (orchestrator/learner/worker). Without the provider SDKs, RUN_OFFLINE=false
# would crash on import of openai/anthropic.
ARG INSTALL_PROVIDERS=""
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# System deps for cryptography / psycopg
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY . .
RUN pip install --no-cache-dir .
RUN if [ -n "$INSTALL_PROVIDERS" ]; then pip install --no-cache-dir ".[providers]"; fi

EXPOSE 8000 8001 8002 8003 8004
CMD python -m uvicorn ${SERVICE}.main:app --host 0.0.0.0 --port ${PORT:-8000}
