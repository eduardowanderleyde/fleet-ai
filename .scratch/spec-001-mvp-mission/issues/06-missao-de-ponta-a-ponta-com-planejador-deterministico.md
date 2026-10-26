# 06: Missão de ponta a ponta com o planejador determinístico

**What to build:** O núcleo do MVP. `POST /v1/missions` recebe "leve o tb1 até a doca de carga", o planejador determinístico reconhece a intenção "mover até lugar nomeado", executa o plano `get_robot_status` → `move_robot` → `wait_for_arrival` pelo despachante de ferramentas, e o tb1 chega de verdade no SimFleet em processo. `GET /v1/missions/{id}` mostra status, passos e texto final. Esta fatia cria a porta de planejador, o despachante e o formato da missão que os tickets seguintes reaproveitam.

**Blocked by:** 05

**Status:** ready-for-agent

- [ ] Porta de planejador definida (instrução, escopo opcional, despachante → status, passos, texto final); planejador determinístico é o padrão da configuração
- [ ] Despachante único com as cinco ferramentas do MVP (`list_robots`, `get_robot_status`, `move_robot`, `wait_for_arrival`, `cancel_navigation`); nenhuma outra
- [ ] Lugares nomeados e apelidos vêm da configuração do cenário lida pelo Fleet AI
- [ ] `POST /v1/missions` → 202 com `mission_id` e `status: "running"`; `GET` de id desconhecido → 404
- [ ] Teste de aceitação: "leve o tb1 até a doca de carga" termina `completed`, com 3 passos na ordem, `planner: "deterministic"`, `language: "pt"`, texto final em português com a pose final, e o tb1 a até 5 cm do lugar
- [ ] Mover um robô FUUT: o plano para no `move_robot` com `is_error: true`, missão `completed` e texto final explicando que o papel não permite movimento
- [ ] Instrução sem intenção reconhecida → `not_understood`, nenhum passo, 3 exemplos no texto final
