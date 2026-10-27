# 08: Escopo de robô e tempo máximo da missão

**What to build:** Uma missão pode ser restrita a um robô (`robot_id` no pedido). O despachante reescreve à força o `robot_id` de todo comando, qualquer que seja o planejador. Missões que estouram o tempo máximo terminam `incomplete` e cancelam a navegação em curso, e a espera do Executor respeita o tempo que resta da missão. O encerramento garantido e as falhas do backend são do ticket 13.

**Blocked by:** 06, 13

**Status:** ready-for-agent

- [ ] Missão com `robot_id: "tb1"` e instrução "leve o tb2 até a doca": o passo `move_robot` registrado tem `robot_id: "tb1"`, o tb1 se move e o tb2 não; o texto final deixa claro que a missão estava restrita ao tb1
- [ ] `list_robots` continua listando a frota numa missão com escopo (só leitura)
- [ ] O escopo é aplicado no despachante, então vale para qualquer planejador (verificado no ticket 10 também)
- [ ] Tempo máximo de missão estourado → `incomplete`, e a navegação em curso é cancelada com verificação no backend; o texto final relata o resultado do cancelamento (`confirmed`, `ambiguous` ou `not_confirmed`) sem afirmar mais do que ele (teste `test_mission_timeout_cancels_navigation_and_reports_the_outcome`)
- [ ] A espera do Executor dentro de uma missão usa o menor entre o timeout do Executor e o tempo que resta da missão (padrões 120 s e 60 s), de modo que a missão nunca espere além do seu tempo máximo (teste `test_executor_wait_respects_the_remaining_mission_time`)
- Movido para o ticket 13: "Backend de frota indisponível → missão `failed` com mensagem; outras missões e o serviço seguem funcionando"

## Comments

- 2026-10-26 (ticket 05): o Executor só converte em `FleetBackendError` a falha do `ros2 service call` no Fleet UI. Backend fora do ar (erro de conexão do `httpx2`), HTTP 5xx ou resposta que não é JSON ainda escapam como exceções do `httpx2`; converter no adaptador ao implementar "backend de frota indisponível → missão `failed`".

- 2026-10-26 (ticket 06), **prioridade**: hoje uma exceção na execução da missão (`FleetBackendError`, erro de conexão, `ExecutorTimeout`) escapa da tarefa em segundo plano e a missão fica em `running` para sempre. Cobrir com `failed` (backend) e `incomplete` (tempo) conforme a SPEC-001.
