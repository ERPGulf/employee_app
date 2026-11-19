#!/usr/bin/env bash
# Push 2FA: plays the mobile app with curl. Use a real browser for the sign-in;
# this script is the "phone" (register_device, pending, respond,
# update_push_token, unregister).
#
# Run on the Ubuntu server (needs OpenSSL 3, curl, python3). macOS openssl
# (LibreSSL) cannot make these signatures.
# Contract: developer guide > Frappe app tab (employee_app.TwoFA.api.*).
#
# Usage:  ./docs/push2fa_phone.sh <command> [args]
#   keys                    make the fake phone's Ed25519 key pair (once)
#   register <code>         enrol the phone; <code> = 6 digits from Microsoft/Google Authenticator
#   pending                 phone: is a sign-in waiting? saves request_id
#   respond allow|deny      phone: answer the saved request
#   push-token <token>      phone: update_push_token
#   unregister              phone: delete the device record
#   neg-badsig | neg-skew | neg-replay     negative tests
#
# Settings (env vars):
# Required: SITE and USER_ID, for example
#   SITE=https://erp.example.com:8443 USER_ID=user@example.com ./docs/push2fa_phone.sh keys
SITE="${SITE:?set SITE, e.g. SITE=https://erp.example.com:8443}"
USER_ID="${USER_ID:?set USER_ID, the ERPNext user to test with}"
DEVICE_ID="${DEVICE_ID:-curl-test-device-1}"
DIR="${DIR:-$HOME/push2fa-test}"

set -euo pipefail
API="$SITE/api/method/employee_app.TwoFA.api"
mkdir -p "$DIR"
cd "$DIR"

# ---------------------------------------------------------------- helpers

# POST JSON, print the HTTP status and the body; body also saved to last.json
post() {
	local url="$1" body="$2"; shift 2
	local code
	code=$(curl -sS -o last.json -w '%{http_code}' -X POST "$url" \
		-H "Content-Type: application/json" -d "$body" "$@")
	echo "HTTP $code"
	cat last.json; echo
}

# read a value from last.json, e.g.  jget request.request_id
jget() {
	python3 - "$1" <<'PY'
import json, sys
def walk(d, path):
	for k in path:
		d = d.get(k) if isinstance(d, dict) else None
	return d
data = json.load(open("last.json"))
path = sys.argv[1].split(".")
v = walk(data, path)
if v is None and isinstance(data, dict):
	v = walk(data.get("message"), path)  # Frappe wraps some replies in "message"
print("" if v is None else v)
PY
}

# Ed25519-sign the lines given as arguments, joined with \n, no trailing newline
sign() {
	local IFS=$'\n'
	printf '%s' "$*" > msg.txt
	openssl pkeyutl -sign -inkey dev.key -rawin -in msg.txt | base64 -w0
}

need() { [ -f "$1" ] || { echo "Missing $1. Run: $0 $2"; exit 1; }; }

# signed request for a phone endpoint: signed_post <endpoint> [field=value ...]
signed_post() {
	need dev.key keys
	local ep="$1"; shift
	local ts="${TS_OVERRIDE:-$(date +%s)}"
	local lines=("$ep" "$USER_ID" "$DEVICE_ID" "$ts")
	local extra=""
	for kv in "$@"; do
		lines+=("${kv#*=}")
		extra+=", \"${kv%%=*}\": \"${kv#*=}\""
	done
	local sig; sig=$(sign "${lines[@]}")
	[ -n "${SIG_TAMPER:-}" ] && sig="A${sig:1}"
	post "$API.$ep" "{\"user\": \"$USER_ID\", \"device_id\": \"$DEVICE_ID\", \"ts\": $ts, \"sig\": \"$sig\"$extra}"
}

# ---------------------------------------------------------------- commands

cmd="${1:-help}"; shift || true
case "$cmd" in

keys)
	openssl genpkey -algorithm ed25519 -out dev.key
	openssl pkey -in dev.key -pubout -outform DER | tail -c 32 | base64 -w0 > pub.b64
	echo "Key pair in $DIR. Public key: $(cat pub.b64)"
	;;

register)
	need dev.key keys
	code="${1:?give the 6-digit code from the authenticator app}"
	post "$API.register_device" "{\"user\": \"$USER_ID\", \"code\": \"$code\",
		\"device_id\": \"$DEVICE_ID\", \"public_key\": \"$(cat pub.b64)\",
		\"push_token\": \"curl-dummy-token\", \"platform\": \"android\", \"app_id\": \"curl-test\"}"
	echo "Expect: {\"status\": \"ok\", \"push\": ...}"
	;;

pending)
	signed_post pending
	req=$(jget request.request_id)
	[ -n "$req" ] && { echo "$req" > request_id.txt; echo "Saved request_id. Next: $0 respond allow"; } \
		|| echo "Nothing waiting."
	;;

respond)
	need request_id.txt pending
	action="${1:?allow or deny}"
	signed_post respond "request_id=$(cat request_id.txt)" "action=$action"
	echo "Expect result: approved / denied / expired. The browser should react within 2 seconds."
	;;

push-token)
	signed_post update_push_token "push_token=${1:?give a token}"
	;;

unregister)
	signed_post unregister
	;;

neg-badsig)
	echo "Expect 401 bad_signature:"
	SIG_TAMPER=1 signed_post pending
	;;

neg-skew)
	echo "Expect 401 clock_skew with server_time:"
	TS_OVERRIDE=$(( $(date +%s) - 300 )) signed_post pending
	;;

neg-replay)
	need request_id.txt pending
	echo "Second answer to the same request. Expect result: expired"
	signed_post respond "request_id=$(cat request_id.txt)" "action=allow"
	;;

*)
	sed -n '2,20p' "$0"
	;;
esac
