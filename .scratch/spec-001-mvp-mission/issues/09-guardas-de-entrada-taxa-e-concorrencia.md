# 09: Guardas de entrada, taxa por IP, concorrência e conflito de escopo

**What to build:** O Fleet AI recusa pedidos abusivos antes de planejar qualquer coisa: instrução vazia ou longa demais, mais missões por IP do que o permitido por minuto ou por dia, e mais missões simultâneas do que o limite global. As recusas têm códigos HTTP e corpo padronizados. A memória de missões tem teto. Além disso, o planejador determinístico recusa a missão quando a instrução cita um robô diferente do escopo (SPEC-001, "Conflito de escopo"), sem enviar nenhum comando; a reescrita estrutural no despachante continua valendo para qualquer planejador.

**Blocked by:** 06

**Status:** resolved

- [x] Instrução vazia ou acima do limite (padrão 300 caracteres) → 422 `{"error", "message"}`, sem nenhum passo executado
- [x] `robot_id` com formato inválido → 422
- [x] Missão acima do limite por minuto do mesmo IP (padrão 10) → 429 com `Retry-After`; outro IP não é afetado
- [x] Limite diário por IP (padrão 100) → 429
- [x] Missão acima do limite de simultâneas (padrão 4) → 429; ao terminar uma missão, a vaga é liberada
- [x] `X-Forwarded-For` só é considerado se a conexão vier de um proxy confiável configurado; sem isso, trocar o cabeçalho não escapa do limite
- [x] Acima do teto de missões retidas (padrão 500), as mais antigas são descartadas; `GET` delas → 404
- [x] Todos os limites vêm da configuração; os testes usam valores pequenos
- [x] Conflito de escopo: com `robot_id: "tb1"`, uma instrução que cita outro robô do cenário (id ou apelido de outro robô) ou uma referência com cara de robô fora do cenário ("tb9") termina `not_understood`, sem nenhum passo, com texto que nomeia o robô citado e o robô do escopo; nada se move
- [x] Com `robot_id: "tb1"`, uma instrução que cita o próprio tb1 (por id ou apelido, como "robô 1") ou não cita robô nenhum segue normalmente com o tb1
- [x] A reescrita do `robot_id` no despachante continua protegendo a execução com qualquer planejador (o teste do ticket 08 com o planejador de teste segue verde)

## Testes previstos

Seam: API HTTP do Fleet AI em processo, contra o SimFleet do warehouse (SPEC-001), com clientes ASGI de IPs diferentes, relógio de teste para as janelas de taxa e planejadores de teste que contam chamadas ou seguram missões em execução.

| Critério | Teste |
|---|---|
| Instrução e escopo no mesmo robô (`tb1`/`tb1`, e `robô 1`/`tb1`) | `test_instruction_naming_the_scoped_robot_runs_normally` (parametrizado) |
| Outro robô do cenário (`tb2`/`tb1`) | `test_instruction_naming_another_robot_conflicts_with_the_scope` |
| Robô fora do cenário (`tb9`/`tb1`) | `test_instruction_naming_an_unknown_robot_conflicts_with_the_scope` |
| Instrução sem robô com escopo `tb1` | `test_instruction_without_a_robot_uses_the_scoped_robot` |
| Garantia estrutural preservada | `test_scope_is_enforced_by_the_dispatcher_for_any_planner` (ticket 08, sem mudança) |
| Instrução vazia ou longa demais; limite exato aceito | `test_empty_or_too_long_instruction_is_rejected_before_planning`, `test_instruction_at_the_length_limit_is_accepted` |
| `robot_id` inválido e corpo malformado | `test_invalid_body_or_robot_id_is_rejected_before_planning` (parametrizado) |
| Taxa por minuto, por IP | `test_missions_per_minute_are_limited_per_ip` |
| Taxa por dia | `test_missions_per_day_are_limited_per_ip` |
| Concorrência e liberação da vaga | `test_concurrent_missions_are_limited_and_the_slot_is_released` |
| `X-Forwarded-For` | `test_forwarded_for_from_an_untrusted_peer_does_not_escape_the_limit`, `test_forwarded_for_from_a_trusted_proxy_identifies_the_client` |
| Teto de missões retidas | `test_missions_beyond_the_retention_limit_drop_the_oldest` |
| Configuração | `test_limits_come_from_the_environment`, `test_mission_time_limit_comes_from_the_environment`, `test_invalid_limit_in_the_environment_prevents_startup` |

Fora deste ticket: orçamento de tokens e custos (ADR-0004) e a política de `ExecutorTimeout` (ADR-0006, proposto).

## Comments

- 2026-10-27: acrescentado o conflito de escopo a pedido do dono, depois da revisão do ticket 08. Antes, a missão com escopo `tb1` e instrução "leve o tb2…" era executada no tb1 em silêncio (risco registrado no ticket 08).
- 2026-10-27 (implementação), **riscos restantes**:
  - O limitador de taxa guarda, por IP, os instantes das missões aceitas nas últimas 24 h; um IP que não volta nunca sai da memória. Com muitos endereços distintos (por exemplo IPv6, ou `X-Forwarded-For` atrás de um proxy confiável mal configurado), o consumo cresce sem limite. Resolver com uma varredura periódica ou um teto de IPs antes do deploy público. **Tratado no ticket 14** (limpeza oportunista; consultar não cria registro), sem teto absoluto.
  - Requisições inválidas (422) não gastam cota: não planejam nada, mas são ilimitadas. O proxy reverso do deploy pode limitar a taxa bruta.
  - Taxa, concorrência e retenção vivem em memória de um processo; com mais de um processo ou réplica, cada um conta sozinho (Redis fica para a spec de deploy).
  - Uma missão ainda rodando pode ser descartada pela retenção e passar a dar 404 no `GET`, embora termine normalmente. **Tratado no ticket 14** (retenção segura).
  - O status `rejected` fica reservado e não é usado (SPEC-001 ajustada).
