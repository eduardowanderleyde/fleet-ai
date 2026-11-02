# 12: Docker Compose local com os dois serviços

**What to build:** Fleet AI e SimFleet sobem juntos com Docker Compose na máquina local, do jeito que vão rodar na VPS: imagens próprias, usuário não-root, healthchecks, limite de memória, SimFleet só na rede interna e Fleet AI publicado apenas em `127.0.0.1`. Uma missão com o planejador determinístico funciona dentro do Compose, sem nenhuma chave de API. Não há deploy.

**Blocked by:** 07, 08, 09, 11, 13, 14

**Status:** resolved

- [x] Duas imagens com usuário não-root e sistema de arquivos somente leitura
- [x] Healthchecks de liveness: o Fleet AI usa `/health/live` (nunca a readiness, para não reiniciar o container quando o backend de frota cai) e o SimFleet usa `/health`; o Fleet AI só sobe depois do SimFleet saudável
- [x] SimFleet sem porta publicada; Fleet AI publicado em `127.0.0.1`, porta configurável
- [x] Limites de memória definidos; o SimFleet com o warehouse fica abaixo de 256 MB
- [x] O Compose não declara nenhuma variável de chave de API
- [x] Roteiro documentado de verificação: subir, criar a missão "leve o tb1 até a doca de carga", ver `completed`, derrubar
- [x] `SIMFLEET_TIME_SCALE=3` para a demonstração e `restart: unless-stopped` nos dois serviços
- [x] Logs com rotação (`json-file`, 3 arquivos de 10 MB) e limites de CPU e processos
- [x] Shutdown limpo: a sondagem de readiness em andamento é cancelada e aguardada, o cliente HTTP do Executor criado pela aplicação é fechado e um Executor injetado não é fechado
- [x] A imagem final traz a interface web (HTML, CSS e JavaScript) e os cenários do SimFleet
- [x] Roteiro real (`scripts/compose-smoke.sh`) num projeto exclusivo, na porta 8010, com limpeza garantida e sem limpeza global do Docker
- [x] README: subir, parar, reiniciar, logs, túnel SSH, histórico em memória e o aviso de que o Compose não autoriza exposição pública

## Comments

- 2026-10-27 (ticket 11): definir como o proxy reverso trata `/health` (readiness, pode responder 503) e `/health/live`; uma indisponibilidade temporária do backend de frota não pode derrubar o acesso à interface web nem à consulta do histórico de missões.
- 2026-10-28 (ticket 11), **ponto de atenção**: no shutdown do Fleet AI, encerrar corretamente a sondagem de readiness compartilhada que estiver em andamento (cancelar e aguardar a tarefa no ciclo de vida da aplicação), para que `docker compose stop` não deixe tarefas pendentes nem avisos "Task was destroyed but it is pending".
- 2026-10-28 (ticket 15): este ticket é só local, com o Fleet AI em `127.0.0.1`, e **não depende** do ticket 15. Qualquer passo que publique a API fora de `127.0.0.1` (proxy reverso, deploy na VPS) depende do ticket 15 concluído.
- 2026-11-02 (implementação):
  - **Imagens:** um `Dockerfile` com dois alvos, `fleet-ai` e `simfleet` (D1). A construção usa `uv` 0.13.6 e `python:3.12-slim-bookworm`, fixados por tag (D4), e instala pelo `uv.lock` (`--frozen --no-dev --no-editable`). A etapa final leva só o ambiente pronto, roda como uid 10001 e sem ferramentas de desenvolvimento.
  - **Rede e portas:** o SimFleet fica só na rede `internal` (`internal: true`), sem porta no host. O Fleet AI está na `internal` e na `edge`, publicado em `127.0.0.1:${FLEET_AI_PORT:-8000}`. A porta padrão é a mesma da demo (D2).
  - **Shutdown:** o `lifespan` do `create_app` chama `Readiness.aclose()` e fecha o Executor só quando foi a aplicação que o criou. O uvicorn tem `--timeout-graceful-shutdown 10` e o Compose `stop_grace_period: 20s`. Missões em andamento esperam até 10 s e depois são interrompidas, sem gravação e sem cancelamento automático de robôs (D3, ADR-0006).
- 2026-11-02, **código de saída 143:** com o uvicorn 0.54, um `docker compose stop` limpo termina com 143 (128 + SIGTERM), porque o uvicorn reenvia o sinal a si mesmo depois do shutdown completo (`signal.raise_signal` em `uvicorn/server.py`). O roteiro aceita 0 ou 143 junto com "Application shutdown complete" e "Finished server process" no log; 137 (SIGKILL) seria o prazo estourado.
- 2026-11-02, **requisição esperando a sondagem no shutdown:** termina como `500 internal_error` (o middleware de cabeçalhos transforma o cancelamento num erro), sem ficar pendurada e sem expor detalhes. Só acontece durante a parada.
- 2026-11-02, **smoke real:** passou de ponta a ponta. Memória medida: Fleet AI 38,6 MiB de 384 MiB e SimFleet 54 MiB de 256 MiB. A parada levou menos de 1 s, sem "Task was destroyed". Nas duas rodadas que falharam durante o ajuste do roteiro, a limpeza removeu os containers e as redes do projeto, e a demo e os outros containers da VPS não foram tocados.
- 2026-11-02, **provas de sanidade:**
  - Compose, Dockerfile e roteiro: 19 mutações (bind público, porta no SimFleet, rede não interna, readiness como liveness, sem restart, escala 1, planejador LLM, variável de chave, sem rotação, sem limite de memória, sem dependência saudável, root, sem shutdown gracioso num alvo, interface excluída da imagem, `.env` na imagem, smoke na 8000, smoke sem `trap`, `docker system prune`). Todas derrubam o teste estático; o shutdown gracioso num só alvo sobrevivia na primeira rodada e passou a ser conferido por alvo.
  - Shutdown: 5 mutações. Todas derrubam algum teste; "cancelar sem esperar" sobrevivia e ganhou um teste direto do `Readiness.aclose()`.
- 2026-11-02, **revisão de Standards:**
  - Documentação e comentários em português e identificadores em inglês, como manda o CLAUDE.md; nenhuma variável de chave de API (ADR-0004).
  - Julgamentos:
    - **Duplicação no `compose.yaml`:** a configuração de segurança é repetida nos dois serviços em vez de usar âncoras YAML, para ficar explícita e verificável pelo teste estático sem um parser de YAML.
    - **Teste estático por texto e indentação:** é frágil a reformatações. Fica assim para não adicionar dependência; o `compose-smoke.sh` é a verificação real.
- 2026-11-02, **revisão de Spec:** os critérios do ticket e os pedidos adicionais estão cobertos.
  - **Fica para o deploy** (comentário de 2026-10-27): como o proxy reverso trata `/health` e `/health/live`.
  - **Novo para o deploy:** no Compose, todo acesso pelo host chega ao Fleet AI com o IP do gateway da rede do Docker. O limite de taxa por IP trata todos os clientes como um só; antes de qualquer exposição pública, configurar `FLEET_AI_TRUSTED_PROXIES` com o proxy.
  - **Sem domínio, HTTPS, proxy, autenticação ou LLM real** neste ticket.
