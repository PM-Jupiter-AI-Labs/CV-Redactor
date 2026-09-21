#!/usr/bin/env bash
#
# Start both halves inside the one container a Hugging Face Space gives you.
#
# A Space exposes exactly one port. The UI is what people come for, so that is
# the one they get; the API listens on the loopback interface only, where the UI
# can reach it and nothing outside the container can. That is a feature here:
# none of the endpoints have authentication, so an internet-facing API would be
# an open document-processing service running on someone else's account.
#
# Both processes are supervised by this script rather than by an init system,
# because there are two of them and the rule is simple: if either dies, the
# container dies, and the Space restarts it. A half-running Space that serves a
# UI with a dead API behind it is worse than one that is plainly down.

set -euo pipefail

API_HOST="127.0.0.1"
API_PORT="${API_PORT:-8000}"
UI_PORT="${PORT:-7860}"

# The UI talks to the API over loopback; nothing here is reachable externally.
export CV_REDACTOR_API_URL="http://${API_HOST}:${API_PORT}"

log() { printf '[entrypoint] %s\n' "$*"; }

log "starting API on ${API_HOST}:${API_PORT}"
uvicorn frontend.api.main:app \
    --host "${API_HOST}" \
    --port "${API_PORT}" \
    --log-level warning &
API_PID=$!

shutdown() {
    log "shutting down"
    kill -TERM "${API_PID}" "${UI_PID:-}" 2>/dev/null || true
}
trap shutdown TERM INT

# Wait for the API to answer before the UI can be clicked, so nobody sees a
# "cannot reach the API" error that would have fixed itself in two seconds.
log "waiting for the API to become healthy"
for _ in $(seq 1 60); do
    if ! kill -0 "${API_PID}" 2>/dev/null; then
        log "the API exited during startup; see the log above"
        exit 1
    fi
    if python -c "
import sys, httpx
try:
    sys.exit(0 if httpx.get('${CV_REDACTOR_API_URL}/api/v1/health', timeout=2).status_code == 200 else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
        log "API is healthy"
        break
    fi
    sleep 1
done

log "starting UI on 0.0.0.0:${UI_PORT}"
streamlit run streamlit_app.py \
    --server.port "${UI_PORT}" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false \
    --server.maxUploadSize "${CV_REDACTOR_MAX_UPLOAD_MB:-25}" &
UI_PID=$!

# Whichever process exits first takes the container with it. `|| EXIT_CODE=$?`
# rather than a bare `wait`, because `set -e` would otherwise abort the script
# on a non-zero exit before the cleanup below could run.
EXIT_CODE=0
wait -n "${API_PID}" "${UI_PID}" || EXIT_CODE=$?
log "a process exited with status ${EXIT_CODE}; stopping the other"
shutdown
exit "${EXIT_CODE}"
