ARG SERVICE=gateway
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# System deps for cryptography / psycopg
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY . .
RUN pip install --no-cache-dir .

EXPOSE 8000 8001 8002 8003 8004
CMD python -m uvicorn ${SERVICE}.main:app --host 0.0.0.0 --port ${PORT:-8000}
