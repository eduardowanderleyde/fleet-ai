# 05: Executor, adaptadores de frota e suíte de contrato

**What to build:** O Executor do `fleet-ui@a57a3b1` é portado (com a correção de pose por robô) para o subconjunto do MVP e passa a falar o contrato normalizado (ADR-0005): listar robôs, status de um robô, mover, aguardar o fim da navegação e cancelar com confirmação. Dois adaptadores de frota: `sim`, que repassa as respostas do SimFleet, e `fleet_ui`, o único lugar que traduz as respostas brutas do Fleet UI. Uma única suíte de contrato, parametrizada por adaptador, prova que os dois dão o mesmo resultado normalizado.

**Blocked by:** 04

**Status:** ready-for-agent

- [ ] Código portado cita arquivo e commit de origem no `fleet-ui`; nenhum merge entre repositórios; aviso de licença MIT do `fleet-ui` preservado
- [ ] Status de um robô usa a pose de `poses[robot_id]`, com fallback para `pose`, como na referência
- [ ] Comando recusado vira erro do Executor carregando `error_code` e `message`
- [ ] Aguardar o fim da navegação faz polling até o estado sair de `navigating` e devolve estado final, `last_error` e pose; intervalo e timeout configuráveis; timeout vira erro do Executor
- [ ] O Executor lembra, por robô, o destino ativo que ele mesmo enviou e se já o viu em `navigating`
- [ ] Cancelar com verificação: `cancel` aceito seguido de polling até o estado sair de `navigating`, com resultado `confirmed` (destino ativo enviado por este Executor, visto em `navigating`, cancel aceito e primeira leitura seguinte `idle`), `ambiguous` (cancel aceito e robô em `failed`, por exemplo `NAV2_ABORTED`, ou destino ativo desconhecido para este Executor) ou `not_confirmed` (continua `navigating` até o timeout)
- [ ] `NAV2_ABORTED` nunca produz `confirmed` por si só
- [ ] Adaptador `fleet_ui` traduz: HTTP 200 com `success=False` e `error_code='X'` no texto do `ros2 service call` → `error_code: X`; 403 "não declarado em roles.yaml" → `UNKNOWN_ROBOT`; 403 "não permite movimento" → `ROLE_NOT_ALLOWED`; 422 do FastAPI → `INVALID_REQUEST`; texto sem `success=False` → sucesso
- [ ] O fake do Fleet UI emite as respostas **brutas** da referência (HTTP 200 com texto de terminal, 403 do backend, 422 do FastAPI, navegação assíncrona) e pode ser configurado para, depois de um cancelamento aceito, mostrar `idle` ou `failed` / `NAV2_ABORTED` na leitura seguinte, como o orquestrador real; documenta de quais arquivos e commit vieram
- [ ] A mesma suíte de contrato passa com os dois adaptadores: listar, status, mover até chegar, robô desconhecido, papel sem movimento, já navegando, destino impossível (`NAV2_REJECTED`), cancelar navegando e cancelar parado (`CANCEL_FAILED`)

## Testes previstos

Seams: Executor contra o SimFleet em processo (adaptador `sim`) e contra o fake do Fleet UI (adaptador `fleet_ui`), via transporte ASGI em memória do `httpx2`.

| Critério | Teste |
|---|---|
| Suíte de contrato | `tests/contract/` parametrizado por adaptador: `test_move_until_arrival`, `test_unknown_robot`, `test_fixed_robot_cannot_move`, `test_already_navigating`, `test_impossible_destination_fails_with_nav2_rejected`, `test_cancel_while_navigating_is_confirmed`, `test_cancel_while_idle_fails` |
| Tradução bruta | `test_fleet_ui_adapter_translates_raw_service_call_output` (parametrizado com textos reais do `ros2 service call`) |
| Cancelamento confirmado | `test_cancel_of_own_destination_followed_by_idle_is_confirmed` (os dois adaptadores) |
| `NAV2_ABORTED` após cancelar | `test_cancel_followed_by_nav2_aborted_is_ambiguous_not_confirmed` (adaptador `fleet_ui`) |
| Destino de outro cliente | `test_cancel_of_a_destination_this_executor_did_not_send_is_ambiguous` |
| Continua navegando | `test_cancel_that_never_stops_the_robot_is_not_confirmed` |
| Timeout | `test_wait_for_navigation_times_out` |

## Comments

- 2026-10-26 (ticket 01): a suíte usa `httpx2` (o Starlette 1.10 depreciou `httpx` no `TestClient`) e `httpx` não está instalado. Portar o Executor já sobre `httpx2.AsyncClient`; o `ASGITransport` existe no `httpx2` 2.16.
