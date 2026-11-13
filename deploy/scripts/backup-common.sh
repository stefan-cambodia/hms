#!/bin/sh
# Shared by the backup service scripts (sourced, not run).
# Backups contain guest personal data: never world-readable. Status files
# (no personal data: names, sizes, checksums, outcomes) are readable by the
# API, which shows them on the Backups screen.
: "${PGHOST:=db}" "${PGUSER:?}" "${PGDATABASE:?}"
BACKUP_DIR=${BACKUP_DIR:-/backups}
CONTROL=${BACKUP_CONTROL_DIR:-/control}
STATUS="$CONTROL/status"
REQUESTS="$CONTROL/requests"
UUID_RE='^[0-9a-f]\{8\}-[0-9a-f]\{4\}-[0-9a-f]\{4\}-[0-9a-f]\{4\}-[0-9a-f]\{12\}$'
FILE_RE='^hms-[0-9]\{8\}T[0-9]\{6\}Z\.dump$'

now_iso() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# Write a status file atomically, readable by the API.
publish() { # name, content
  [ -d "$STATUS" ] || return 0
  printf '%s\n' "$2" > "$STATUS/.$1.tmp" && chmod 0644 "$STATUS/.$1.tmp" && mv "$STATUS/.$1.tmp" "$STATUS/$1"
}

# The operation in progress (shown live on the Backups screen).
current() { # kind, step, request_id, by
  publish current.json "$(jq -cn --arg kind "$1" --arg step "$2" --arg id "${3:-}" --arg by "${4:-}" \
    --arg at "$(now_iso)" '{kind: $kind, step: $step, request_id: $id, requested_by: $by, since: $at}')"
}
idle() { rm -f "$STATUS/current.json"; }

# One line per backup or restore run, newest last; the last 500 are kept.
record_run() { # json
  [ -d "$STATUS" ] || return 0
  printf '%s\n' "$1" >> "$STATUS/runs.jsonl"
  tail -n 500 "$STATUS/runs.jsonl" > "$STATUS/.runs.tmp" && chmod 0644 "$STATUS/.runs.tmp" \
    && mv "$STATUS/.runs.tmp" "$STATUS/runs.jsonl"
}

# List of the backups on disk, newest first (metadata written at backup time;
# older backups without it are listed with what the files tell).
reindex() {
  [ -d "$STATUS" ] || return 0
  list=$(ls -1t "$BACKUP_DIR"/hms-*.dump 2>/dev/null || true)
  {
    for f in $list; do
      meta="${f%.dump}.json"
      if [ -f "$meta" ]; then
        cat "$meta"
      else
        sum=$(cut -d' ' -f1 "$f.sha256" 2>/dev/null || true)
        jq -cn --arg file "$(basename "$f")" --argjson bytes "$(wc -c < "$f")" --arg sha256 "$sum" \
          '{file: $file, bytes: $bytes, sha256: $sha256, trigger: "unknown"}'
      fi
    done
  } | jq -cs '.' > "$STATUS/.backups.tmp" && chmod 0644 "$STATUS/.backups.tmp" \
    && mv "$STATUS/.backups.tmp" "$STATUS/backups.json"
}
