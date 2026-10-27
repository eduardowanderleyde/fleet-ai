# 08: Escopo de robô e tempo máximo da missão

**What to build:** Uma missão pode ser restrita a um robô (`robot_id` no pedido). O despachante reescreve à força o `robot_id` de todo comando, qualquer que seja o planejador. Missões que estouram o tempo máximo terminam `incomplete` e cancelam a navegação em curso, e a espera do Executor respeita o tempo que resta da missão. O encerramento garantido e as falhas do backend são do ticket 13.

**Blocked by:** 06, 13

**Status:** resolved

- [x] Missão com `robot_id: "tb1"` e instrução "leve o tb2 até a doca": o passo `move_robot` registrado tem `robot_id: "tb1"`, o tb1 se move e o tb2 não; o texto final deixa claro que a missão estava restrita ao tb1
- [x] `list_robots` continua listando a frota numa missão com escopo (só leitura)
- [x] O escopo é aplicado no despachante, então vale para qualquer planejador (verificado no ticket 10 também)
- [x] Tempo máximo de missão estourado → `incomplete`, e a navegação em curso é cancelada com verificação no backend; o texto final relata o resultado do cancelamento (`confirmed`, `ambiguous` ou `not_confirmed`) sem afirmar mais do que ele (teste `test_mission_timeout_cancels_navigation_and_reports_the_outcome`)
- [x] A espera do Executor dentro de uma missão usa o menor entre o timeout do Executor e o tempo que resta da missão (padrões 120 s e 60 s), de modo que a missão nunca espere além do seu tempo máximo (teste `test_executor_wait_respects_the_remaining_mission_time`)
- Movido para o ticket 13: "Backend de frota indisponível → missão `failed` com mensagem; outras missões e o serviço seguem funcionando"

## Comments

- 2026-10-26 (ticket 05): o Executor só converte em `FleetBackendError` a falha do `ros2 service call` no Fleet UI. Backend fora do ar (erro de conexão do `httpx2`), HTTP 5xx ou resposta que não é JSON ainda escapam como exceções do `httpx2`; converter no adaptador ao implementar "backend de frota indisponível → missão `failed`".

- 2026-10-26 (ticket 06), **prioridade**: hoje uma exceção na execução da missão (`FleetBackendError`, erro de conexão, `ExecutorTimeout`) escapa da tarefa em segundo plano e a missão fica em `running` para sempre. Cobrir com `failed` (backend) e `incomplete` (tempo) conforme a SPEC-001.

- 2026-10-27 (implementação), **riscos restantes**:
  - Com escopo no tb1, uma instrução que cita outro robô (inclusive um desconhecido, como "tb9") é executada no tb1, sem acusar o robô citado; o texto final começa por "Missão restrita ao tb1". É a semântica estrutural pedida; o `robot_id` do escopo ainda não é validado (ticket 09). **Será corrigido no ticket 09**: o planejador determinístico passa a recusar o conflito com `not_understood` (SPEC-001, "Conflito de escopo"), mantendo a reescrita no despachante.
  - O tempo total de uma missão pode passar do tempo máximo em até o prazo de confirmação do cancelamento (`cancel_grace`, 5 s por padrão); o cancelamento inteiro (leitura, POST e verificação) fica sob esse prazo.
  - Se o prazo do Executor for menor que o tempo restante da missão, vale o `ExecutorTimeout` do ticket 13: `incomplete` sem cancelamento.
  - Só a navegação enviada pela própria missão é cancelada no tempo máximo; uma navegação iniciada por outro cliente não é tocada.
