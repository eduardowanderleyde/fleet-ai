# 06: Missão de ponta a ponta com LLM roteirizado

**What to build:** O núcleo do MVP. `POST /v1/missions` recebe uma instrução, cria a missão e roda o Planner em segundo plano; `GET /v1/missions/{id}` mostra status, passos, texto final e uso. O Planner (portado do `fleet-ui`) conversa com uma porta de LLM e despacha as cinco ferramentas do MVP pelo Executor. Nos testes, o LLM roteirizado dirige a missão "leve o tb1 até X" e o tb1 chega de verdade no SimFleet em processo.

**Blocked by:** 05

**Status:** ready-for-agent

- [ ] Porta de LLM definida (sistema, mensagens, ferramentas, limite de tokens → blocos, motivo de parada, uso); LLM roteirizado implementado, registra o que recebeu e falha alto se o roteiro acabar
- [ ] Ferramentas do MVP expostas ao modelo: `list_robots`, `get_robot_status`, `move_robot`, `wait_for_arrival`, `cancel_navigation`; nenhuma outra
- [ ] `POST /v1/missions` → 202 com `mission_id` e `status: "running"`; `GET` de id desconhecido → 404
- [ ] Teste de aceitação: roteiro `list_robots` → `get_robot_status` → `move_robot` → `wait_for_arrival` → texto final; a missão termina `completed`, com 4 passos na ordem, texto final e pose do tb1 no destino
- [ ] Missão com robô inexistente: o resultado de erro da ferramenta volta ao modelo e a missão termina `completed` com o texto do modelo explicando a recusa
- [ ] Uso (tokens de entrada e saída) somado por missão a partir do que o LLM devolve
- [ ] Sistema de prompt mantém as regras do `fleet-ui` e acrescenta "aguardar chegada antes de declarar sucesso" e "responder no idioma da instrução"
