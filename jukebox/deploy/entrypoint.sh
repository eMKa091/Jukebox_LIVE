#!/bin/sh
# Restore-then-replicate.
#
# On a cold start, pull the newest snapshot from object storage before the app
# opens the database. On a warm start the local file is already newest and
# litestream leaves it alone. Either way the app never starts against an empty
# database it then treats as authoritative -- which is how the legacy system
# lost votes.
#
# Replication is on when LITESTREAM_BUCKET is set. What Litestream replicates,
# and where to, is in /etc/litestream.yml (deploy/litestream.yml in the repo).
set -eu

SERVE="uvicorn app.main:app --host 0.0.0.0 --port 8080 --proxy-headers --forwarded-allow-ips=*"

if [ -n "${LITESTREAM_BUCKET:-}" ]; then
    : "${LITESTREAM_ENDPOINT:?LITESTREAM_BUCKET is set but LITESTREAM_ENDPOINT is not}"
    echo "litestream: restoring ${JUKEBOX_DB} if there is no local copy"
    litestream restore -if-db-not-exists -if-replica-exists "${JUKEBOX_DB}"
    echo "litestream: replicating to ${LITESTREAM_BUCKET}"
    exec litestream replicate -exec "${SERVE}"
fi

echo "WARNING: LITESTREAM_BUCKET is not set. The database is NOT being"
echo "         replicated. Do not run a real event like this."
exec ${SERVE}
