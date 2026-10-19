# P2P Energy Engine - container image
# Build:  docker build -t p2p-engine .
# Run:    docker run -p 8000:8000 -v p2p-data:/data p2p-engine        (SQLite, no AWS needed)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY *.py ./
COPY static ./static

# run as a non-root user; /data holds the SQLite file when DB_BACKEND=sqlite
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /data \
 && chown -R appuser:appuser /app /data
USER appuser

# defaults (override with -e / --env-file / compose)
ENV DB_BACKEND=sqlite \
    SQLITE_PATH=/data/p2p.db \
    AWS_REGION=ap-southeast-2

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1

# ONE process only: the simulation clock lives in memory, so never add --workers and never run two copies
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
