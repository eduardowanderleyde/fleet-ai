# 13: Toda missão termina

**What to build:** Enquanto o processo do Fleet AI estiver ativo, nenhuma missão fica presa em `running`. Falhas do backend de frota terminam a missão em `failed`, uma navegação que não termina no prazo do Executor termina em `incomplete` (sem cancelamento automático, dizendo que o robô pode continuar navegando), e qualquer outra exceção ou o cancelamento da tarefa terminam em `failed`. Em todos os casos `finished_at` é preenchido, os passos já executados ficam preservados, o passo que falhou aparece com `is_error: true`, e a resposta não expõe detalhes internos; o diagnóstico vai para os logs. A fronteira HTTP dos adaptadores separa recusas válidas do contrato de respostas inesperadas (SPEC-001, "Encerramento garantido da missão"; ADR-0005, "Fronteira de erro dos adaptadores").

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] Nos dois adaptadores, falha de transporte (conexão recusada), HTTP 5xx, corpo que não é JSON e JSON sem os campos do contrato viram `FleetBackendError`
- [ ] Recusas 4xx **válidas** do contrato continuam sendo recusas (`CommandRefused` com o `error_code`); 4xx **inesperadas** (400, 401, 404, 405), 4xx com corpo malformado, `error_code` desconhecido ou incoerente com o status, e qualquer erro HTTP nas consultas viram `FleetBackendError`
- [ ] Backend de frota indisponível durante a missão → `failed`, texto final genérico ("backend de frota indisponível") no idioma da instrução, último passo com `is_error: true` e `result.error: "backend_unavailable"`
- [ ] Falha do `ros2 service call` no Fleet UI e código fora do contrato (`NAV2_UNAVAILABLE`) → `failed` pelo mesmo caminho
- [ ] Navegação que não termina no prazo do Executor (`ExecutorTimeout`) → `incomplete`; último passo `wait_for_arrival` com `is_error: true` e `result.error: "navigation_timeout"`; o texto final diz que a navegação não terminou no prazo e que o robô pode continuar navegando; nenhum `cancel` é enviado
- [ ] Exceção inesperada no planejador ou no despachante → `failed` com texto genérico de erro interno; o texto e os passos não contêm a mensagem da exceção
- [ ] Cancelamento da tarefa da missão (`asyncio.CancelledError`) → a missão fica `failed` com `finished_at`, e o cancelamento é repropagado (a tarefa termina cancelada, não suprimida)
- [ ] Toda falha tratada gera um log estruturado com `mission_id`, tipo da falha e a mensagem diagnóstica; a resposta da missão nunca contém mensagens do backend, texto de exceção, URLs internas ou credenciais
- [ ] Em todos os casos acima, os passos executados antes da falha continuam na missão e `finished_at` não é nulo
- [ ] Depois de uma missão `failed` por backend indisponível, o serviço continua respondendo e uma nova missão com o backend de volta termina `completed`
- [ ] A detecção de idioma sai do planejador determinístico para um módulo próprio, usado também pelos textos de falha

## Testes previstos

Seams: API HTTP do Fleet AI em processo (SPEC-001), com transportes de teste que simulam backend fora do ar ou respostas inválidas, e o fake do Fleet UI do ticket 05; suíte de contrato nos dois adaptadores (ticket 05). **Seam adicional a confirmar:** o cancelamento da tarefa só é observável executando a missão numa tarefa `asyncio` e cancelando-a, então o teste de `CancelledError` chama a função pública que executa uma missão (exposta pelo módulo de missões), não a API HTTP.

| Critério | Teste |
|---|---|
| Fronteira: transporte e 5xx | `test_unreachable_backend_raises_fleet_backend_error`, `test_server_error_raises_fleet_backend_error` (suíte de contrato, dois adaptadores) |
| Fronteira: corpo inválido | `test_non_json_or_incomplete_body_raises_fleet_backend_error` (parametrizado) |
| Fronteira: 4xx | `test_valid_contract_refusals_stay_refusals`, `test_unexpected_4xx_raises_fleet_backend_error` (parametrizado: 400, 401, 404, 405, 409 sem `error_code`, 403 com mensagem desconhecida) |
| Backend fora do ar | `test_mission_fails_when_the_fleet_backend_is_unreachable` |
| Respostas inválidas | `test_mission_fails_when_the_backend_answers_garbage` (parametrizado) |
| Fleet UI | `test_mission_fails_when_the_fleet_ui_service_call_fails` |
| Prazo do Executor | `test_navigation_that_does_not_end_in_time_makes_the_mission_incomplete` (também confere que nenhum `cancel` chegou ao backend) |
| Exceção inesperada | `test_unexpected_error_fails_the_mission_without_leaking_details` |
| Cancelamento | `test_cancelled_mission_is_failed_and_the_cancellation_propagates` |
| Logs sem vazamento | `test_failures_are_logged_with_the_mission_id` (`caplog`) e asserções de ausência nos testes acima |
| Invariante | `test_every_mission_reaches_a_terminal_state` (parametrizado com todos os cenários acima; prova de sanidade desligando a garantia) |
| Recuperação do serviço | `test_service_keeps_working_after_a_failed_mission` |

## Comments

- 2026-10-27: criado a partir da prioridade registrada no ticket 08 (comentário do ticket 06). Herda do ticket 08 o critério "backend de frota indisponível → missão `failed`".
