# One image, one process. Everything the app needs is in here except the
# database file, which lives on a mounted volume, and the secrets, which come
# from the environment.

FROM python:3.12-slim AS base

# Litestream streams the SQLite write-ahead log to object storage continuously.
# It is the whole reason SQLite is safe here: the recovery point is seconds,
# not "whenever an admin last pressed a button".
FROM litestream/litestream:0.3 AS litestream

FROM base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY --from=litestream /usr/local/bin/litestream /usr/local/bin/litestream

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# The volume mount point. JUKEBOX_DB points here.
RUN mkdir -p /data
ENV JUKEBOX_DB=/data/jukebox.db

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=4s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).status==200 else 1)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
