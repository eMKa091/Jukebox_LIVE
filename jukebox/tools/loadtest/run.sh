#!/bin/sh
# run.sh <app dir> <label> <phones> <arrive s> <window s>
set -eu
S=$(cd "$(dirname "$0")" && pwd)
APP=$1; LABEL=$2; N=$3; ARRIVE=$4; WINDOW=$5
PY="$APP/.venv/bin/python"
DB=$S/db-$LABEL; rm -rf "$DB"; mkdir -p "$DB"
ulimit -n 8192
cd "$APP"
"$PY" "$S/seed.py" "$APP" "$DB/jukebox.db" 420 > "$DB/seed.out"
JUKEBOX_DEV=1 JUKEBOX_DB="$DB/jukebox.db" "$PY" -m uvicorn app.main:app --port 8766 --log-level warning > "$DB/server.log" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  curl -s -o /dev/null http://127.0.0.1:8766/readyz && break
  perl -e 'select(undef,undef,undef,0.5)'
done
read SLUG RID EID < "$DB/seed.out"
echo "== $LABEL: $N phones, arriving over $ARRIVE s, voting over $WINDOW s"
"$PY" "$S/phones.py" http://127.0.0.1:8766 "$SLUG" "$RID" "$EID" "$N" "$ARRIVE" "$WINDOW"
echo "server cpu $(ps -o cputime= -p $SERVER)  rss $(ps -o rss= -p $SERVER) KB"
sqlite3 "$DB/jukebox.db" "select 'votes '||count(*)||', voters '||count(distinct voter_id) from votes where round_id=$RID;"
echo "server log lines: $(wc -l < "$DB/server.log")"; tail -5 "$DB/server.log"
