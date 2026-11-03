#!/usr/bin/env bash
# Roda a suíte de avaliação contra o modelo local (SPEC-005, ticket 02).
#
# Sobe um Ollama temporário só para a avaliação, com o mesmo volume de modelos do
# Compose, publicado em 127.0.0.1:11435 e sem saída para a internet necessária;
# remove o container no fim, mesmo se algo falhar. Não toca no Compose em uso.
#   ./scripts/ollama-eval.sh [--only injecao]
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="ollama/ollama:0.40.13"
MODEL="${FLEET_EVAL_MODEL:-qwen2.5:3b}"
NAME="fleet-ai-ollama-eval-$$"
PORT=11435
VOLUME="fleet-ai_ollama-models"

docker volume inspect "${VOLUME}" >/dev/null 2>&1 || {
  echo "O volume ${VOLUME} não existe; baixe o modelo antes:" >&2
  echo "  docker compose -f compose.yaml -f compose.llm.yaml --profile setup run --rm ollama-pull" >&2
  exit 1
}
if ss -tln | grep -q ":${PORT} "; then
  echo "A porta ${PORT} já está em uso" >&2
  exit 1
fi

cleanup() { docker rm -f "${NAME}" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "${NAME}" --init --read-only --tmpfs /tmp \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 4g --cpus 3 --pids-limit 256 \
  -e OLLAMA_HOST=0.0.0.0:11434 -e OLLAMA_NUM_PARALLEL=1 -e OLLAMA_KEEP_ALIVE=1h \
  -v "${VOLUME}:/root/.ollama:ro" -p "127.0.0.1:${PORT}:11434" "${IMAGE}" >/dev/null

for _ in $(seq 1 60); do
  curl -fsS "http://127.0.0.1:${PORT}/api/tags" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://127.0.0.1:${PORT}/api/tags" | grep -q "\"${MODEL}\"" || {
  echo "O modelo ${MODEL} não está no volume" >&2
  exit 1
}

uv run python -m fleet_eval --planner llm \
  --llm-url "http://127.0.0.1:${PORT}/v1" --llm-model "${MODEL}" "$@"
