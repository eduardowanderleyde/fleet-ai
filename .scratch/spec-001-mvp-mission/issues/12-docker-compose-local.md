# 12: Docker Compose local com os dois serviços

**What to build:** Fleet AI e SimFleet sobem juntos com Docker Compose na máquina local, do jeito que vão rodar na VPS: imagens próprias, usuário não-root, healthchecks, limite de memória, SimFleet só na rede interna e Fleet AI publicado apenas em `127.0.0.1`. Uma missão com o planejador determinístico funciona dentro do Compose, sem nenhuma chave de API. Não há deploy.

**Blocked by:** 07, 08, 09, 11, 13, 14

**Status:** ready-for-agent

- [ ] Duas imagens com usuário não-root e sistema de arquivos somente leitura
- [ ] Healthchecks de liveness: o Fleet AI usa `/health/live` (nunca a readiness, para não reiniciar o container quando o backend de frota cai) e o SimFleet usa `/health`; o Fleet AI só sobe depois do SimFleet saudável
- [ ] SimFleet sem porta publicada; Fleet AI publicado em `127.0.0.1`, porta configurável
- [ ] Limites de memória definidos; o SimFleet com o warehouse fica abaixo de 256 MB
- [ ] O Compose não declara nenhuma variável de chave de API
- [ ] Roteiro documentado de verificação: subir, criar a missão "leve o tb1 até a doca de carga", ver `completed`, derrubar

## Comments

- 2026-10-27 (ticket 11): definir como o proxy reverso trata `/health` (readiness, pode responder 503) e `/health/live`; uma indisponibilidade temporária do backend de frota não pode derrubar o acesso à interface web nem à consulta do histórico de missões.
- 2026-10-28 (ticket 11), **ponto de atenção**: no shutdown do Fleet AI, encerrar corretamente a sondagem de readiness compartilhada que estiver em andamento (cancelar e aguardar a tarefa no ciclo de vida da aplicação), para que `docker compose stop` não deixe tarefas pendentes nem avisos "Task was destroyed but it is pending".
