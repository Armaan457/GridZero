FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY *.py nodes_config.yaml ./
COPY static ./static

RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /data \
 && chown -R appuser:appuser /app /data
USER appuser

ENV DB_BACKEND=sqlite \
    SQLITE_PATH=/data/p2p.db

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
