#!/bin/sh
# Restore-then-replicate.
#
# On a cold start, pull the newest snapshot from object storage before the app
# opens the database. On a warm start the local file is already newest and
# litestream leaves it alone. Either way the app never starts against an empty
# database it then treats as authoritative -- which is how the legacy system
# lost votes.
set -eu

if [ -n "${LITESTREAM_REPLICA_URL:-}" ]; then
    echo "litestream: restoring ${JUKEBOX_DB} if the replica is newer"
    litestream restore -if-db-not-exists -if-replica-exists "${JUKEBOX_DB}"
    echo "litestream: replicating"
    exec litestream replicate -exec \
        "uvicorn app.main:app --host 0.0.0.0 --port 8080 --proxy-headers --forwarded-allow-ips='*'"
fi

echo "WARNING: LITESTREAM_REPLICA_URL is not set. The database is NOT being"
echo "         replicated. Do not run a real event like this."
exec uvicorn app.main:app --host 0.0.0.0 --port 8080 --proxy-headers --forwarded-allow-ips='*'
