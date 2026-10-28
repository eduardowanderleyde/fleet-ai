# 10: Planejador LLM com LLM roteirizado, desligado por padrão

**What to build:** O loop de tool use do `fleet-ui` é portado como segunda implementação da porta de planejador, dependendo de uma porta de LLM. A única implementação de LLM é o roteirizado. O planejador LLM só roda com configuração explícita; por padrão o serviço usa o determinístico. Assim o caminho agêntico fica testado e pronto para uma integração futura com modelos reais, sem nenhum custo agora.

**Blocked by:** 08, 13

**Status:** resolved

- [x] Porta de LLM definida (sistema, mensagens, ferramentas, limite de tokens → blocos, motivo de parada, uso); LLM roteirizado registra o que recebeu e falha alto se o roteiro acabar
- [x] Planner portado cita arquivo e commit de origem; regras de sistema do `fleet-ui` mantidas, mais "aguardar chegada antes de declarar sucesso" e "responder no idioma da instrução"
- [x] Com planejador `llm` e o roteiro `list_robots` → `get_robot_status` → `move_robot` → `wait_for_arrival` → texto, a missão termina `completed` com 4 passos, `planner: "llm"` e o tb1 no destino
- [x] Erro de ferramenta volta ao modelo como `tool_result` com `is_error`, sanitizado: só `error_code` e mensagens do Fleet AI, nunca texto bruto do backend nem exceção interna
- [x] Roteiro que nunca para de pedir ferramentas → `incomplete` após o limite de turnos (padrão 8, configurável), com os passos preservados
- [x] No máximo 4 chamadas de ferramenta executadas por turno (configurável); as excedentes recebem `tool_result` com `is_error` e nunca chegam ao despachante
- [x] Ferramenta desconhecida e `input` fora do schema viram `tool_result` de erro sem executar, inclusive quando repetidos em vários turnos
- [x] Backend indisponível → `failed`; `ExecutorTimeout` → `incomplete` sem cancelamento (ADR-0006); exceção do LLM, roteiro esgotado ou resposta inválida → `failed`; `CancelledError` propaga
- [x] Resposta final com navegação da missão ainda ativa → `incomplete`, com texto dizendo que a navegação pode continuar e que não houve cancelamento confirmado; sem cancelamento automático
- [x] Conflito de escopo (instrução cita outro robô) recusado **antes de qualquer planejador**: nenhuma chamada ao LLM, nenhuma ferramenta executada
- [x] Escopo de robô do ticket 08 vale também aqui: reescrita estrutural do despachante (roteiro pede tb2 sem citar robô na instrução, passo registra tb1)
- [x] Configuração padrão → planejador determinístico; `llm` exige configuração explícita e LLM roteirizado injetado no `create_app`; sem LLM injetado, adaptador diferente de `scripted` ou planejador desconhecido → falha explícita na inicialização
- [x] `/health`: `planner: "llm"` e `llm_enabled: false` com o roteirizado
- [x] Nenhum SDK, chave ou chamada de rede além da frota: a missão LLM só faz chamadas registradas ao backend de frota

## Testes previstos

Seam: API HTTP do Fleet AI em processo, com o LLM roteirizado injetado no `create_app`, SimFleet em processo (e fake do Fleet UI), transporte de frota que registra chamadas e o pedido recebido pelo roteirizado (sistema, ferramentas, `tool_result`).

| Garantia | Teste |
|---|---|
| Missão completa | `test_llm_mission_completes_with_four_steps` (4 passos, `planner: "llm"`, tb1 no destino) |
| Contrato do LLM | `test_llm_receives_system_rules_and_exactly_the_five_tools` (regras do fleet-ui mais as duas novas; nomes das cinco ferramentas) |
| Erro sanitizado | `test_tool_error_reaches_the_model_sanitized` (recusa do fake do Fleet UI com texto bruto em português: o `tool_result` tem só `error_code` e mensagem do Fleet AI) |
| Limite de turnos | `test_endless_tool_requests_end_incomplete_after_the_turn_limit` (padrão 8 e valor configurado; passos preservados; LLM chamado exatamente N vezes) |
| Várias chamadas por resposta | `test_multiple_tool_calls_in_one_response` (3 chamadas executadas em ordem; 6 chamadas → 4 executadas, 2 com `is_error` sem passo e sem chamada ao backend; limite configurável) |
| Inválidas repetidas | `test_repeated_invalid_tool_calls_never_reach_the_dispatcher` (ferramenta desconhecida e `input` fora do schema em todos os turnos → nenhuma chamada ao backend, `incomplete` no limite) |
| Erros que encerram | `test_llm_mission_terminal_outcomes` (parametrizado: backend fora do ar → `failed`; `ExecutorTimeout` → `incomplete` sem `cancel`; exceção do LLM, roteiro esgotado, `tool_use` sem blocos → `failed`; `max_tokens` → `incomplete`; nenhum detalhe interno na missão) |
| Cancelamento | `test_llm_mission_cancelled_error_propagates_and_time_limit_cancels_navigation` |
| Resposta final com navegação ativa | `test_final_answer_while_navigating_ends_incomplete_without_cancel` (texto avisa que pode continuar e que não houve cancelamento confirmado; nenhum `cancel` no backend) |
| Conflito antes do planejador | `test_scope_conflict_is_refused_before_any_planner` (parametrizado: determinístico e LLM; LLM chamado zero vezes, zero chamadas ao backend, zero passos) |
| Reescrita estrutural | `test_llm_tool_calls_are_rewritten_to_the_scope` (roteiro pede tb2; passo e backend registram tb1) |
| Configuração | `test_planner_configuration` (padrão determinístico; `llm` sem LLM injetado, adaptador `openai`, planejador desconhecido → `ValueError` explícito na inicialização) |
| Health | `test_health_reports_llm_planner_without_enabling_llm` |
| Custo zero | `test_llm_mission_makes_no_network_calls_besides_the_fleet` (só URLs da frota registradas; nenhuma variável `*_API_KEY` lida) |

## Comments

- 2026-10-26 (ticket 06): o critério "despachante com as cinco ferramentas, nenhuma outra" do ticket 06 não é observável pela API com o planejador determinístico. Verificar aqui: as ferramentas que o LLM roteirizado recebe são exatamente `list_robots`, `get_robot_status`, `move_robot`, `wait_for_arrival`, `cancel_navigation`, e um `tool_use` com outro nome vira erro.
- 2026-10-28 (implementação), **notas e riscos restantes**:
  - O conflito de escopo agora é verificado antes de qualquer planejador (`ScopeGuard`). Efeito colateral: uma instrução com escopo que cita outro robô **e** pede duas ações passa a ser recusada pelo conflito, e não por "uma ação por missão". As duas respostas são `not_understood` sem ferramenta.
  - O modelo recebe resultados sanitizados: recusas viram `error_code` com mensagem do Fleet AI; no estado do robô, `last_error` fora dos códigos do contrato vira `NAV_ERROR` e um `role` que não é identificador vira `UNKNOWN`. Os **passos da missão** continuam registrando a mensagem da recusa como antes (comportamento do despachante, comum aos dois planejadores, anterior a este ticket).
  - A validação dos argumentos é própria (campos do schema, `robot_id` texto não vazio, números finitos), não um validador de JSON Schema completo; basta para as cinco ferramentas do MVP.
  - O uso fictício de tokens existe na porta, mas nada o consome (ADR-0004).
