#!/usr/bin/env bash
# Phase 1 end-to-end smoke test.
# Exercises the full clinician flow against a running local backend:
#   register -> login -> me -> transcribe (real audio) -> history list ->
#   history detail -> delete one -> history list (empty) -> delete account ->
#   confirm token revoked
#
# Requires the backend to be running on $BASE_URL (default http://localhost:8000)
# and the audio fixture at backend/tests/fixtures/test11-yt_chest_pain.mp3.
#
# Usage:
#   ./scripts/smoke-test.sh                 # against http://localhost:8000
#   BASE_URL=http://localhost:8000 ./scripts/smoke-test.sh
#
# Exits non-zero on the first failed assertion.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SAMPLE_AUDIO="${SAMPLE_AUDIO:-$ROOT_DIR/backend/tests/fixtures/test11-yt_chest_pain.mp3}"
BASE_URL="${BASE_URL:-http://localhost:8000}"

# Each run uses a fresh email so the script is repeatable without manual cleanup.
SUFFIX="$(date +%s)-$$"
EMAIL="smoke+${SUFFIX}@example.com"
PASSWORD="SmokeTestPassword!1"

# ── Helpers ──────────────────────────────────────────────────────────────────

# Pull a top-level JSON field by name. Uses python so we avoid an external jq
# dependency on Windows / Codespaces.
json_field() {
  local field="$1"
  python -c "import json,sys; d=json.load(sys.stdin); v=d.get('$field'); print('' if v is None else v)"
}

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$expected" != "$actual" ]]; then
    echo "FAIL: $label: expected '$expected', got '$actual'" >&2
    exit 1
  fi
  echo "  ok: $label = $actual"
}

assert_nonempty() {
  local label="$1" value="$2"
  if [[ -z "$value" ]]; then
    echo "FAIL: $label was empty" >&2
    exit 1
  fi
  echo "  ok: $label is non-empty"
}

require_file() {
  if [[ ! -f "$1" ]]; then
    echo "FAIL: required file not found: $1" >&2
    exit 1
  fi
}

# ── Pre-flight ───────────────────────────────────────────────────────────────

echo "==> Pre-flight"
require_file "$SAMPLE_AUDIO"
echo "  audio fixture: $SAMPLE_AUDIO"

# Confirm the backend is reachable before doing anything else. A failure here
# usually means the user forgot to run dev-backend.sh.
HEALTH_CODE="$(curl -s -o /dev/null -w '%{http_code}' "$BASE_URL/health")"
assert_eq "GET /health status" "200" "$HEALTH_CODE"

# ── 1. Register ──────────────────────────────────────────────────────────────

echo "==> 1. POST /api/auth/register"
REGISTER_BODY="$(curl -s -X POST "$BASE_URL/api/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"first_name\":\"Smoke\",\"last_name\":\"Test\",\"specialty\":\"general\"}")"
TOKEN="$(printf '%s' "$REGISTER_BODY" | json_field access_token)"
assert_nonempty "access_token from register" "$TOKEN"

# ── 2. Login ─────────────────────────────────────────────────────────────────

echo "==> 2. POST /api/auth/login"
LOGIN_BODY="$(curl -s -X POST "$BASE_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")"
LOGIN_TOKEN="$(printf '%s' "$LOGIN_BODY" | json_field access_token)"
assert_nonempty "access_token from login" "$LOGIN_TOKEN"
TOKEN="$LOGIN_TOKEN"

# Wrong password should be rejected — confirms auth path is wired correctly.
WRONG_CODE="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"definitely-wrong\"}")"
assert_eq "wrong password rejected" "401" "$WRONG_CODE"

# ── 3. /me ───────────────────────────────────────────────────────────────────

echo "==> 3. GET /api/auth/me"
ME_BODY="$(curl -s -H "Authorization: Bearer $TOKEN" "$BASE_URL/api/auth/me")"
ME_EMAIL="$(printf '%s' "$ME_BODY" | json_field email)"
assert_eq "/me returns the right email" "$EMAIL" "$ME_EMAIL"

# ── 4. Transcribe ────────────────────────────────────────────────────────────

# The 45-second guard reads X-Audio-Duration-Seconds. We pass 180 so the guard
# does not short-circuit the upload. faster-whisper will transcribe the
# real fixture so this step can take a minute or two.
echo "==> 4. POST /api/transcribe (this can take 1-2 minutes)"
TRANSCRIBE_BODY="$(curl -s --max-time 600 -X POST "$BASE_URL/api/transcribe" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Audio-Duration-Seconds: 180" \
  -F "file=@$SAMPLE_AUDIO" \
  -F "encounter_type=acute_visit")"

TRANSCRIBE_SUCCESS="$(printf '%s' "$TRANSCRIBE_BODY" | json_field success)"
assert_eq "transcribe success flag" "True" "$TRANSCRIBE_SUCCESS"

TRANSCRIPT_TEXT="$(printf '%s' "$TRANSCRIBE_BODY" | json_field transcription)"
assert_nonempty "transcription text" "$TRANSCRIPT_TEXT"

# ── 5. History list ──────────────────────────────────────────────────────────

echo "==> 5. GET /api/history"
HISTORY_BODY="$(curl -s -H "Authorization: Bearer $TOKEN" "$BASE_URL/api/history")"
HISTORY_LEN="$(printf '%s' "$HISTORY_BODY" | python -c 'import json,sys;print(len(json.load(sys.stdin)))')"
assert_eq "history length after one upload" "1" "$HISTORY_LEN"

ENTRY_ID="$(printf '%s' "$HISTORY_BODY" | python -c 'import json,sys;print(json.load(sys.stdin)[0]["id"])')"
assert_nonempty "history entry id" "$ENTRY_ID"

# ── 6. History detail ────────────────────────────────────────────────────────

echo "==> 6. GET /api/history/$ENTRY_ID"
DETAIL_BODY="$(curl -s -H "Authorization: Bearer $TOKEN" "$BASE_URL/api/history/$ENTRY_ID")"
ENTITY_COUNT="$(printf '%s' "$DETAIL_BODY" | python -c 'import json,sys;print(len(json.load(sys.stdin)["entities"]))')"
SOAP_PRESENT="$(printf '%s' "$DETAIL_BODY" | python -c 'import json,sys;d=json.load(sys.stdin); s=d.get("soap_note") or {}; print(int(any((s.get(k) or "").strip() for k in ("subjective","objective","assessment","plan"))))')"
echo "  entities returned: $ENTITY_COUNT"
assert_eq "soap_note has at least one populated section" "1" "$SOAP_PRESENT"

# ── 7. Delete one ────────────────────────────────────────────────────────────

echo "==> 7. DELETE /api/history/$ENTRY_ID"
DEL_CODE="$(curl -s -o /dev/null -w '%{http_code}' -X DELETE -H "Authorization: Bearer $TOKEN" "$BASE_URL/api/history/$ENTRY_ID")"
assert_eq "delete-one status" "204" "$DEL_CODE"

# ── 8. History empty ─────────────────────────────────────────────────────────

echo "==> 8. GET /api/history (expect empty)"
HISTORY_BODY2="$(curl -s -H "Authorization: Bearer $TOKEN" "$BASE_URL/api/history")"
HISTORY_LEN2="$(printf '%s' "$HISTORY_BODY2" | python -c 'import json,sys;print(len(json.load(sys.stdin)))')"
assert_eq "history empty after delete" "0" "$HISTORY_LEN2"

# ── 9. Delete account ────────────────────────────────────────────────────────

echo "==> 9. DELETE /api/auth/me"
ACCT_CODE="$(curl -s -o /dev/null -w '%{http_code}' -X DELETE -H "Authorization: Bearer $TOKEN" "$BASE_URL/api/auth/me")"
assert_eq "account-delete status" "204" "$ACCT_CODE"

# ── 10. Token revoked ────────────────────────────────────────────────────────

echo "==> 10. GET /api/auth/me (expect 401 after account delete)"
POST_DELETE_CODE="$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOKEN" "$BASE_URL/api/auth/me")"
assert_eq "post-delete /me status" "401" "$POST_DELETE_CODE"

echo
echo "PASS: full Phase 1 smoke completed for $EMAIL"
