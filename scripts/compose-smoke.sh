#!/usr/bin/env bash
# Roteiro real do Compose (ticket 12): sobe num projeto exclusivo, na porta 8010,
# verifica health, interface, mapa, frota, uma missão completa, o bind local e o
# shutdown, e remove só o que este projeto criou, mesmo se algo falhar.
# Não toca na demo em andamento nem em outros containers; nunca faz limpeza global.
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT="fleet-ai-smoke-$$"
export FLEET_AI_PORT=8010
BASE="http://127.0.0.1:${FLEET_AI_PORT}"
compose() { docker compose -p "${PROJECT}" -f compose.yaml "$@"; }

cleanup() {
  status=$?
  echo "== limpeza do projeto ${PROJECT}"
  compose down --remove-orphans --timeout 20 >/dev/null 2>&1 || true
  exit "${status}"
}
trap cleanup EXIT

fail() { echo "FALHOU: $*" >&2; exit 1; }
ok() { echo "ok  $*"; }
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

if ss -tln | grep -q ":${FLEET_AI_PORT} "; then
  fail "a porta ${FLEET_AI_PORT} já está em uso"
fi

echo "== subindo ${PROJECT} (build e espera pelos healthchecks)"
compose up -d --build --wait --wait-timeout 180

echo "== health"
[ "$(curl -fsS "${BASE}/health/live" | json 'd["status"]')" = alive ] || fail "/health/live"
ok "/health/live alive"
[ "$(curl -fsS "${BASE}/health" | json 'd["status"], d["fleet_adapter"], d["planner"], d["llm_enabled"]')" \
  = "ok sim deterministic False" ] || fail "/health"
ok "/health ok, adaptador sim, planejador determinístico, LLM desligado"
for service in fleet-ai simfleet; do
  health="$(docker inspect -f '{{.State.Health.Status}}' "$(compose ps -q "${service}")")"
  [ "${health}" = healthy ] || fail "${service} está ${health}"
done
ok "healthchecks dos dois containers: healthy"

echo "== interface e arquivos estáticos"
curl -fsS "${BASE}/" | grep -q "Nova missão" || fail "página inicial"
for asset in /static/app.js /static/app.css; do
  headers="$(curl -fsS -D - -o /dev/null "${BASE}${asset}")"
  grep -qi "^content-security-policy: default-src 'self'" <<<"${headers}" || fail "CSP em ${asset}"
done
curl -fsS "${BASE}/static/app.js" | grep -q "textContent" || fail "conteúdo do app.js"
ok "/, /static/app.js e /static/app.css servidos da imagem, com CSP"

echo "== mapa e frota"
[ "$(curl -fsS "${BASE}/v1/map" | json 'd["available"], len(d["places"])')" = "True 7" ] \
  || fail "/v1/map"
curl -fsS "${BASE}/v1/map/image.png" | head -c 8 | od -An -tx1 | grep -q "89 50 4e 47 0d 0a 1a 0a" \
  || fail "PNG do mapa"
[ "$(curl -fsS "${BASE}/v1/fleet" | json 'sorted(r["robot_id"] for r in d["robots"])')" \
  = "['tb1', 'tb2', 'tb3']" ] || fail "/v1/fleet"
ok "mapa com 7 lugares e PNG válido; frota com tb1, tb2 e tb3"

echo "== missão completa"
mission="$(curl -fsS -X POST "${BASE}/v1/missions" -H 'Content-Type: application/json' \
  -d '{"instruction": "leve o tb1 até a doca de carga"}' | json 'd["mission_id"]')"
for _ in $(seq 1 90); do
  status="$(curl -fsS "${BASE}/v1/missions/${mission}" | json 'd["status"]')"
  [ "${status}" != running ] && break
  sleep 1
done
[ "${status}" = completed ] || fail "missão terminou ${status}"
ok "\"leve o tb1 até a doca de carga\" terminou completed"

echo "== bind local e SimFleet sem porta publicada"
[ "$(compose port fleet-ai 8000)" = "127.0.0.1:${FLEET_AI_PORT}" ] || fail "porta do Fleet AI"
listeners="$(ss -tln | awk '{print $4}' | grep ":${FLEET_AI_PORT}$")"
[ "${listeners}" = "127.0.0.1:${FLEET_AI_PORT}" ] || fail "escuta inesperada: ${listeners}"
ok "Fleet AI só em 127.0.0.1:${FLEET_AI_PORT}"
simfleet_id="$(compose ps -q simfleet)"
[ "$(docker inspect -f '{{json .HostConfig.PortBindings}}' "${simfleet_id}")" = "{}" ] \
  || fail "SimFleet com porta publicada"
[ -z "$(docker port "${simfleet_id}")" ] || fail "SimFleet com porta publicada"
ok "SimFleet sem porta publicada no host"

echo "== memória"
docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' \
  "$(compose ps -q fleet-ai)" "${simfleet_id}"

echo "== shutdown"
curl -fsS "${BASE}/health" >/dev/null  # sondagem de readiness recente antes da parada
fleet_ai_id="$(compose ps -q fleet-ai)"
started=$(date +%s)
compose stop --timeout 20 >/dev/null
elapsed=$(( $(date +%s) - started ))
logs="$(docker logs "${fleet_ai_id}" 2>&1)"
grep -q "Application shutdown complete" <<<"${logs}" || fail "shutdown não terminou no Fleet AI"
grep -q "Finished server process" <<<"${logs}" || fail "o processo do Fleet AI não terminou sozinho"
if grep -Eq "Task was destroyed|was never awaited|Unclosed client" <<<"${logs}"; then
  fail "tarefas ou clientes pendentes no shutdown"
fi
for id in "${fleet_ai_id}" "${simfleet_id}"; do
  # 143 = 128 + SIGTERM: o uvicorn reenvia o sinal a si mesmo depois de um shutdown
  # completo. 137 (SIGKILL) seria o prazo de parada estourado.
  code="$(docker inspect -f '{{.State.ExitCode}}' "${id}")"
  if [ "${code}" != 0 ] && [ "${code}" != 143 ]; then
    docker logs --tail 15 "${id}" 2>&1 >&2
    fail "$(docker inspect -f '{{.Name}}' "${id}") saiu com código ${code}"
  fi
done
ok "parada em ${elapsed} s, shutdown completo (sem SIGKILL), sem tarefas de health pendentes"

echo "== tudo certo"
