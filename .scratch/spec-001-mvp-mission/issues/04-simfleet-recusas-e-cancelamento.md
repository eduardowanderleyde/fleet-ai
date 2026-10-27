# 04: SimFleet recusa comandos inválidos, falha navegações e cancela

**What to build:** O SimFleet completa o contrato normalizado de comandos (ADR-0005). Requisições malformadas, robô desconhecido e papel sem movimento são recusados na hora, com o `error_code` da tabela. Destinos bem formados mas impossíveis (ocupados, perto demais de obstáculo, fora do mapa, sem caminho) são aceitos e falham na leitura seguinte do status, com `nav_state: failed` e `last_error: NAV2_REJECTED`, e a causa detalhada vai para um log estruturado. `POST /api/cancel` interrompe a navegação, deixa o robô parado onde está e recusa com `CANCEL_FAILED` quando não há navegação ativa.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] `x`, `y` ou `yaw` ausente, não numérico, infinito ou NaN, ou `robot_id` ausente → `422`, `success: false`, `error_code: INVALID_REQUEST`; nenhum estado muda
- [ ] `go_to_point` ou `cancel` para robô fora do cenário → `403`, `UNKNOWN_ROBOT`
- [ ] `go_to_point` para robô FUUT ou SU → `403`, `ROLE_NOT_ALLOWED`; a pose não muda
- [ ] O papel do robô no cenário é validado ao carregar: valores fora de `MUUT`, `FUUT`, `SU` (por exemplo, `"MUTT"`) impedem o serviço de subir com `ScenarioError` que cita o robô e o papel
- [ ] Destino ocupado, perto demais de obstáculo, fora do mapa ou sem caminho → `200 "Navigation started"`; na leitura seguinte, `nav_state: failed`, `last_error: NAV2_REJECTED`, pose inalterada
- [ ] Cada navegação falhada gera uma linha de log estruturado com robô, destino, `error_code` e causa (`target_occupied`, `target_out_of_map`, `no_path`)
- [ ] Um `go_to_point` válido depois de `failed` é aceito e chega normalmente; `last_error` volta a vazio na chegada
- [ ] `cancel` durante a navegação → `200 {"success": true, "message": "Cancel requested", "error_code": ""}`; a primeira leitura seguinte já mostra `idle` (nunca `failed`), na pose em que estava, e as leituras seguintes não mudam a pose
- [ ] Depois de um `cancel` aceito (robô em `idle`), um novo `go_to_point` é aceito
- [ ] `cancel` com o robô em `idle` ou `failed` → `409`, `success: false`, `error_code: CANCEL_FAILED`, sem efeito colateral

## Testes previstos

Seam: API HTTP do SimFleet em processo, relógio manual injetado; logs capturados pelo mecanismo de captura de logs do pytest (`caplog`).

| Critério | Teste |
|---|---|
| Malformada | `test_malformed_go_to_point_is_rejected_with_invalid_request` (parametrizado) |
| Robô desconhecido | `test_unknown_robot_is_rejected` (go_to_point e cancel) |
| Papel | `test_fixed_robot_cannot_move` (FUUT e SU) |
| Papel inválido no cenário | `test_unknown_role_in_scenario_prevents_startup` |
| Destino impossível | `test_impossible_destination_fails_asynchronously_with_nav2_rejected` (parametrizado por causa) |
| Log da causa | `test_failed_navigation_logs_the_detailed_cause` |
| Recuperação | `test_valid_destination_after_failure_arrives_and_clears_last_error` |
| Cancelar navegando | `test_cancel_stops_the_robot_where_it_is` |
| Novo destino após cancelar | `test_new_destination_after_accepted_cancel_is_accepted` |
| Cancelar sem navegação | `test_cancel_without_active_navigation_fails_with_cancel_failed` |

## Comments

- 2026-10-26 (ticket 02): o papel do robô ainda é texto livre no cenário (`"MUTT"` carregaria sem erro). Ao implementar a recusa por papel, decidir se o cenário passa a validar `MUUT`/`FUUT`/`SU`; no Fleet UI, papel desconhecido apenas não se move.
- 2026-10-26 (grilling): validação do papel no carregamento aprovada pelo dono (ADR-0005).
