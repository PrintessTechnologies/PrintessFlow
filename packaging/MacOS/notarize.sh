#!/bin/bash
# Robustly submit a file to Apple's notary service and wait for the result.
#
# notarytool's own `--wait` polls over the network and exits non-zero on a
# single transient timeout (observed: "The request timed out" on
# /notary/v2/submissions/<id>) even when the submission itself is fine. This
# helper decouples submit from polling and tolerates transient poll/upload
# errors, only failing on a real Invalid/Rejected verdict or a hard timeout.
#
# Usage: notarize.sh <file> <key_path> <key_id> <issuer_id> <team_id>
# Exits 0 only when Apple returns status: Accepted.
set -uo pipefail

FILE="$1"; KEY="$2"; KEY_ID="$3"; ISSUER="$4"; TEAM="$5"
ARGS=(--key "$KEY" --key-id "$KEY_ID" --issuer "$ISSUER" --team-id "$TEAM")

json_field() { python3 -c 'import sys,json;print(json.load(sys.stdin).get("'"$1"'",""))' 2>/dev/null; }

# --- Submit (retry the upload a few times) ---------------------------------
SUB=""
for attempt in 1 2 3 4 5; do
  echo "Submitting $FILE (attempt $attempt)..."
  OUT=$(xcrun notarytool submit "$FILE" "${ARGS[@]}" --output-format json 2>&1)
  echo "$OUT"
  SUB=$(printf '%s' "$OUT" | json_field id)
  [ -n "$SUB" ] && break
  echo "submit attempt $attempt failed; retrying in 20s"
  sleep 20
done
if [ -z "$SUB" ]; then
  echo "::error::Could not submit $FILE to the notary service"
  exit 1
fi
echo "Submission id: $SUB"

# --- Poll for the verdict (tolerate transient errors) ---------------------
# Up to ~30 min: 60 polls x 30s.
for i in $(seq 1 60); do
  sleep 30
  INFO=$(xcrun notarytool info "$SUB" "${ARGS[@]}" --output-format json 2>/dev/null)
  if [ -z "$INFO" ]; then
    echo "poll $i: transient error contacting notary, retrying"
    continue
  fi
  STATUS=$(printf '%s' "$INFO" | json_field status)
  echo "poll $i: status=${STATUS:-unknown}"
  case "$STATUS" in
    Accepted)
      echo "Notarization Accepted (submission $SUB)"
      exit 0
      ;;
    Invalid|Rejected)
      echo "::error::Notarization $STATUS for $FILE — full Apple log follows"
      xcrun notarytool log "$SUB" "${ARGS[@]}" || true
      exit 1
      ;;
  esac
done

echo "::error::Timed out waiting for notarization of $FILE (submission $SUB)"
xcrun notarytool log "$SUB" "${ARGS[@]}" || true
exit 1
