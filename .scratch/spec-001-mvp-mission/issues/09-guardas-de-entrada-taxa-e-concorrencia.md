# 09: Guardas de entrada, taxa por IP, concorrência e conflito de escopo

**What to build:** O Fleet AI recusa pedidos abusivos antes de planejar qualquer coisa: instrução vazia ou longa demais, mais missões por IP do que o permitido por minuto ou por dia, e mais missões simultâneas do que o limite global. As recusas têm códigos HTTP e corpo padronizados. A memória de missões tem teto. Além disso, o planejador determinístico recusa a missão quando a instrução cita um robô diferente do escopo (SPEC-001, "Conflito de escopo"), sem enviar nenhum comando; a reescrita estrutural no despachante continua valendo para qualquer planejador.

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] Instrução vazia ou acima do limite (padrão 300 caracteres) → 422 `{"error", "message"}`, sem nenhum passo executado
- [ ] `robot_id` com formato inválido → 422
- [ ] Missão acima do limite por minuto do mesmo IP (padrão 10) → 429 com `Retry-After`; outro IP não é afetado
- [ ] Limite diário por IP (padrão 100) → 429
- [ ] Missão acima do limite de simultâneas (padrão 4) → 429; ao terminar uma missão, a vaga é liberada
- [ ] `X-Forwarded-For` só é considerado se a conexão vier de um proxy confiável configurado; sem isso, trocar o cabeçalho não escapa do limite
- [ ] Acima do teto de missões retidas (padrão 500), as mais antigas são descartadas; `GET` delas → 404
- [ ] Todos os limites vêm da configuração; os testes usam valores pequenos
- [ ] Conflito de escopo: com `robot_id: "tb1"`, uma instrução que cita outro robô do cenário (id ou apelido de outro robô) ou uma referência com cara de robô fora do cenário ("tb9") termina `not_understood`, sem nenhum passo, com texto que nomeia o robô citado e o robô do escopo; nada se move
- [ ] Com `robot_id: "tb1"`, uma instrução que cita o próprio tb1 (por id ou apelido, como "robô 1") ou não cita robô nenhum segue normalmente com o tb1
- [ ] A reescrita do `robot_id` no despachante continua protegendo a execução com qualquer planejador (o teste do ticket 08 com o planejador de teste segue verde)

## Testes previstos

Seam: API HTTP do Fleet AI em processo, contra o SimFleet do warehouse (SPEC-001). Os testes das guardas de entrada, taxa e concorrência serão listados ao implementar; os de conflito de escopo estão definidos abaixo.

| Critério | Teste |
|---|---|
| Instrução e escopo no mesmo robô (`tb1`/`tb1`, e `robô 1`/`tb1`) | `test_instruction_naming_the_scoped_robot_runs_normally` (parametrizado) |
| Outro robô do cenário (`tb2`/`tb1`) | `test_instruction_naming_another_robot_conflicts_with_the_scope` |
| Robô fora do cenário (`tb9`/`tb1`) | `test_instruction_naming_an_unknown_robot_conflicts_with_the_scope` |
| Instrução sem robô com escopo `tb1` | `test_instruction_without_a_robot_uses_the_scoped_robot` |
| Garantia estrutural preservada | `test_scope_is_enforced_by_the_dispatcher_for_any_planner` (ticket 08, sem mudança) |

Fora deste ticket: orçamento de tokens e custos (ADR-0004) e a política de `ExecutorTimeout` (ADR-0006, proposto).

## Comments

- 2026-10-27: acrescentado o conflito de escopo a pedido do dono, depois da revisão do ticket 08. Antes, a missão com escopo `tb1` e instrução "leve o tb2…" era executada no tb1 em silêncio (risco registrado no ticket 08).
