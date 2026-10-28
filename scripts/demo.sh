#!/usr/bin/env bash
# Demo local do Fleet AI (SPEC-003): SimFleet e Fleet AI só em 127.0.0.1.
# Acesso pelo túnel SSH; nada fica exposto na internet. Ctrl+C encerra os dois.
set -euo pipefail
cd "$(dirname "$0")/.."

FLEET_AI_PORT="${FLEET_AI_PORT:-8000}"
SIMFLEET_PORT="${SIMFLEET_PORT:-8001}"
# A 0,3 m/s a ida até a doca leva ~60 s, o tempo máximo da missão; 3x deixa a demo fluida.
export SIMFLEET_TIME_SCALE="${SIMFLEET_TIME_SCALE:-3}"

uv run uvicorn simfleet.app:create_app --factory --host 127.0.0.1 --port "$SIMFLEET_PORT" &
SIMFLEET_PID=$!
trap 'kill "$SIMFLEET_PID" 2>/dev/null || true' EXIT

echo
echo "Fleet AI em http://127.0.0.1:${FLEET_AI_PORT}/ (SimFleet interno na porta ${SIMFLEET_PORT})."
echo "No seu computador, abra o túnel e depois http://localhost:${FLEET_AI_PORT}/ :"
echo "  ssh -L ${FLEET_AI_PORT}:127.0.0.1:${FLEET_AI_PORT} $(whoami)@$(hostname -f)"
echo

FLEET_AI_FLEET_URL=http://127.0.0.1:"$SIMFLEET_PORT" \
  uv run uvicorn fleet_ai.app:create_app --factory --host 127.0.0.1 --port "$FLEET_AI_PORT"
