#!/bin/sh
# run_worker.sh <app dir> <url> <setup token> <label> <phones> <arrive s> <window s> [spread s]
#
# The load test against the Worker (docs/08, step 8). The object must be
# empty: locally, delete worker/.wrangler/state and restart `pywrangler dev`;
# on Cloudflare, deploy a copy of its own first, so the band's data is never
# touched:  pywrangler deploy --name jukebox-live-loadtest
# Seeds a file the way run.sh does, makes the account `load` through the
# setup page, pushes the file in (scripts/transfer.py), then runs the phones.
set -eu
S=$(cd "$(dirname "$0")" && pwd)
APP=$1; URL=$2; TOKEN=$3; LABEL=$4; N=$5; ARRIVE=$6; WINDOW=$7; SPREAD=${8:-0}
PY="$APP/.venv/bin/python"
DB=$S/db-$LABEL; rm -rf "$DB"; mkdir -p "$DB"
ulimit -n 8192
cd "$APP"
"$PY" "$S/seed.py" "$APP" "$DB/jukebox.db" 420 > "$DB/seed.out"
curl -s -o /dev/null -X POST "$URL/admin/setup" --data-urlencode "token=$TOKEN" \
  --data-urlencode username=load --data-urlencode password=load-test-password \
  --data-urlencode repeat=load-test-password
JUKEBOX_PASSWORD=load-test-password "$PY" scripts/transfer.py push "$DB/jukebox.db" "$URL" load > "$DB/push.out"
read SLUG RID EID < "$DB/seed.out"
echo "== $LABEL: $N phones against $URL, arriving over $ARRIVE s, voting over $WINDOW s, reloads spread over $SPREAD s"
"$PY" "$S/phones.py" "$URL" "$SLUG" "$RID" "$EID" "$N" "$ARRIVE" "$WINDOW" "$SPREAD"
JUKEBOX_PASSWORD=load-test-password "$PY" scripts/transfer.py pull "$URL" load "$DB/after.db" > /dev/null
sqlite3 "$DB/after.db" "select 'votes stored '||count(*)||', voters '||count(distinct voter_id) from votes where round_id=$RID;"
