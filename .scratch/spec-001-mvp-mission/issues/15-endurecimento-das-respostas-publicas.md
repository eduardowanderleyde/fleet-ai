# 15: Endurecimento das respostas públicas de missões

**What to build:** Nenhum texto bruto ou potencialmente sensível vindo do backend de frota, do LLM ou de exceções internas aparece nas respostas públicas do Fleet AI, em especial `GET /v1/missions/{mission_id}`. A sanitização acontece num único ponto, na saída do despachante, para que os passos da missão, o texto final dos dois planejadores e o que o modelo recebe usem a mesma visão controlada. O usuário continua vendo o que importa: status, `error_code`, `nav_state`, pose, resultado do cancelamento e textos do Fleet AI. Encontrado na revisão do ticket 10. **Precisa estar concluído antes de expor a API publicamente** (fora de `127.0.0.1`).

**Blocked by:** 10

**Status:** ready-for-agent

## Campos públicos que hoje podem carregar texto do backend

| Campo público | Origem | Hoje |
|---|---|---|
| `steps[].result.message` (recusa) | `CommandRefused.message`: texto do SimFleet, mensagem do `_require_muut` do Fleet UI ou `message=` do `ros2 service call` | bruto |
| `steps[].result.message` em `cancel_navigation` recusado (tempo máximo) | idem, via `Dispatcher.cancel_active` | bruto |
| `steps[].result.last_error` (`get_robot_status`, `wait_for_arrival`) | `/api/status`, campo não validado pelo adaptador | bruto |
| `steps[].result.role` | `/api/status`, qualquer texto | bruto |
| `steps[].result.robot_ids` (`list_robots`) | `/api/list_robots`, só validado como lista de textos | bruto |
| `final_text` do determinístico ao não chegar (`_not_reached`) | interpola `last_error` | bruto |
| `final_text` do planejador LLM | texto livre do modelo, sem limite de tamanho | livre |
| `steps[].input.robot_id` (planejador LLM, missão sem escopo) | argumento do modelo: texto não vazio, sem limite | livre |
| Corpo do `404` | repete o `mission_id` do caminho | eco |
| Erro não tratado num endpoint | resposta padrão do FastAPI | não testado |

Já controlados e mantidos: textos de falha da missão (`backend_unavailable`, `navigation_timeout`, `cancelled`, `internal_error`), corpo do `/health`, recusas `422`/`429`/`503` da API. Os logs continuam com o detalhe técnico e não são resposta pública.

## Sanitização

- **Um ponto só:** o despachante devolve e registra resultados já sanitizados, e os dois planejadores usam esses resultados. As visões que hoje ficam só no planejador LLM (`_refusal`, `_for_model`) passam a ser a regra geral.
- **Recusas:** `{"error_code", "message"}`, com `message` de uma tabela do Fleet AI por código do contrato (ADR-0005). O texto do backend vai só para o log.
- **Estado do robô:** `last_error` só com códigos do contrato (`""`, `NAV2_REJECTED`, `NAV2_ABORTED`); outro texto vira `NAV_ERROR`. `role` que não é identificador vira `UNKNOWN`.
- **Identificadores:** `robot_id` de robôs e de argumentos do modelo segue `[A-Za-z0-9_-]{1,64}`. Uma lista de robôs fora disso é corpo fora do contrato (`FleetBackendError`, ADR-0005). Um argumento fora disso é `INVALID_INPUT` e não executa.
- **Texto final do determinístico:** usa só valores sanitizados, por exemplo "(NAV2_REJECTED)".
- **Texto final do LLM:** limitado a 2000 caracteres e sem caracteres de controle. É texto gerado pelo modelo, que só viu dados sanitizados; a interface web deve tratá-lo como texto, nunca como HTML.
- **Erros da API:** `404` com mensagem fixa, sem repetir o caminho. Exceção não tratada em endpoint vira `500 {"error": "internal_error", "message": "Internal error"}`, sem stack trace.

## Critérios

- [ ] Nenhum dos campos da tabela acima carrega texto bruto do backend, de exceção interna ou do LLM sem os limites definidos
- [ ] A sanitização vale para os dois planejadores e os dois adaptadores, a partir de um único ponto
- [ ] Informação útil preservada: `error_code`, `nav_state`, pose, resultado do cancelamento, ids dos robôs e textos do Fleet AI
- [ ] A visão que o modelo recebe (ticket 10) continua igual ou mais restrita
- [ ] `404` e `500` com corpos fixos, sem eco nem stack trace
- [ ] O detalhe técnico continua nos logs, para diagnóstico
- [ ] README e SPEC-001 registram que a exposição pública depende deste ticket

## Testes previstos

Seam: API HTTP do Fleet AI em processo, com SimFleet e fake do Fleet UI, transportes de teste que devolvem respostas maliciosas e os dois planejadores (LLM roteirizado injetado). Textos sensíveis fictícios usados em todos: `http://10.0.0.5:8000/internal`, `postgres://admin:s3cret@db:5432`, `Authorization: Bearer sk-test-FAKE`, `Traceback (most recent call last): File "/opt/ros/humble/..."` e `RuntimeError: unexpected`.

| Garantia | Teste |
|---|---|
| Recusa sanitizada | `test_refusal_message_is_replaced_by_a_fleet_ai_message` (parametrizado: cada texto sensível, dois adaptadores, dois planejadores) |
| Cancelamento recusado | `test_refused_cancel_after_the_time_limit_is_sanitized` |
| Estado do robô | `test_status_fields_outside_the_contract_are_sanitized` (`last_error`, `role` com texto sensível) |
| Lista de robôs | `test_robot_ids_outside_the_contract_are_a_backend_error` |
| Texto final do determinístico | `test_unreached_destination_text_uses_only_contract_codes` |
| Texto final do LLM | `test_llm_final_text_is_bounded_and_has_no_control_characters` |
| Argumento do modelo | `test_llm_robot_id_argument_outside_the_pattern_is_invalid_input` |
| Erros inesperados | `test_unexpected_errors_never_reach_public_responses` (exceção no adaptador, no planejador e num endpoint: corpo fixo `500` ou missão `failed` com texto genérico) |
| 404 | `test_unknown_mission_does_not_echo_the_path` |
| Varredura geral | `test_no_sensitive_text_in_any_public_response` (`POST /v1/missions`, `GET /v1/missions/{id}`, `/health`, `/health/live`: nenhum dos textos sensíveis em nenhum corpo) |
| Diagnóstico | `test_backend_detail_still_reaches_the_logs` |
