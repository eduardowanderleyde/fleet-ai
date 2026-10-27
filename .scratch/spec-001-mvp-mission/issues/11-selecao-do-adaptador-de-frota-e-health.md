# 11: Seleção do adaptador de frota, liveness e readiness

**What to build:** O adaptador de frota (`sim`, padrão, ou `fleet_ui`) e a URL do backend vêm da configuração, validada na inicialização sem chamadas de rede; trocar de SimFleet para Fleet UI não exige mudar código. O serviço sobe mesmo com o backend fora do ar. `GET /health/live` diz se o processo está vivo, sem consultar o backend; `GET /health` é a readiness: sonda o backend com prazo, cache e uma única sondagem compartilhada, e responde 200 `ok` ou 503 `degraded`, sem expor nenhum detalhe interno. A readiness não certifica a segurança de robôs físicos. Um checklist manual documenta como validar contra o Fleet UI real (SPEC-001, "Seleção do adaptador e health").

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] `FLEET_AI_FLEET_ADAPTER` aceita só `sim` (padrão) e `fleet_ui`; outro valor impede o serviço de subir com mensagem que lista os valores válidos
- [ ] Com `fleet_ui`, `FLEET_AI_FLEET_URL` é obrigatória; sem ela o serviço não sobe
- [ ] URL com credenciais, esquema diferente de `http`/`https`, sem host, com porta inválida, com `?`, `#` ou `;` impede o serviço de subir, **sem nenhuma chamada de rede**; a mensagem não repete credenciais
- [ ] O serviço sobe com o backend fora do ar; `/health/live` responde 200 e `/health` responde 503 `degraded`
- [ ] `GET /health/live` → `200 {"status": "alive"}` e nunca consulta o backend
- [ ] `GET /health` → `200` com `{"status": "ok", "fleet_adapter", "fleet_backend_reachable": true, "planner": "deterministic", "llm_enabled": false}` quando o backend responde de forma válida, com os dois adaptadores
- [ ] Backend com conexão recusada, mais lento que o prazo de 2 s, com 5xx ou corpo fora do contrato → `503` com `status: "degraded"` e `fleet_backend_reachable: false`; o health responde dentro do prazo
- [ ] Recuperação: com o backend de volta, depois de o cache expirar, `/health` volta a 200 `ok`
- [ ] Cache de 5 s: dentro dele, chamadas ao `/health` não sondam o backend de novo
- [ ] Sondagem única: várias chamadas simultâneas ao `/health` depois de o cache expirar resultam em **uma** sondagem; todas recebem o mesmo resultado; cancelar uma chamada não cancela a sondagem
- [ ] O corpo do `/health` tem só os cinco campos; nunca URL, host, porta, credenciais nem mensagens de erro, em nenhum cenário de falha
- [ ] O teste de aceitação do ticket 06 passa com o adaptador `fleet_ui` apontado para o fake do Fleet UI, sem alterar as asserções
- [ ] Checklist manual no README: subir o Fleet UI real, apontar o Fleet AI, rodar uma missão com o planejador determinístico; avisos de que o Fleet UI não tem autenticação (só rede confiável) e de que a readiness não certifica a segurança de robôs físicos

## Testes previstos

Seams: API HTTP do Fleet AI em processo (SPEC-001). Configuração por variáveis de ambiente; transporte de teste injetado no `create_app` (mesmo padrão da injeção do `executor`) para backend fora do ar, lento, com erro ou fora do contrato, e para contar as chamadas feitas ao backend; relógio injetado para o cache; prazo da sondagem reduzido nos testes. Sem ROS 2: SimFleet em processo e fake do Fleet UI do ticket 05.

| Critério | Teste |
|---|---|
| Padrão `sim` | `test_default_adapter_is_sim` (o `/health` informa `fleet_adapter: "sim"`) |
| `fleet_ui` por configuração | `test_fleet_ui_adapter_is_selected_by_configuration` |
| Adaptador desconhecido | `test_unknown_adapter_prevents_startup` |
| URL obrigatória | `test_fleet_ui_without_url_prevents_startup` |
| URL inválida, sem rede | `test_invalid_fleet_url_prevents_startup_without_network` (parametrizado: credenciais, `ftp`, sem host, porta inválida, `?`, `#`, `;`; o transporte de teste confirma zero chamadas; a mensagem não contém a senha) |
| Sobe com backend fora do ar | `test_service_starts_with_the_backend_down` |
| Liveness | `test_liveness_never_calls_the_backend` |
| Readiness ok | `test_readiness_is_ok_when_the_backend_answers` (parametrizado: `sim`, `fleet_ui`) |
| Falhas | `test_readiness_is_degraded_when_the_backend_fails` (parametrizado: conexão recusada, 5xx, não JSON, fora do contrato) |
| Timeout | `test_readiness_answers_within_the_probe_timeout` |
| Recuperação | `test_readiness_recovers_when_the_backend_comes_back` |
| Cache | `test_readiness_is_cached_for_five_seconds` |
| Sondagem única | `test_concurrent_health_checks_share_a_single_probe` (inclui o cancelamento de uma das chamadas) |
| Sem vazamento | `test_health_never_exposes_backend_details` (nos cenários de falha, o corpo não contém URL, host, porta nem trechos da mensagem de erro) |
| Aceitação com `fleet_ui` | o teste de aceitação do ticket 06, parametrizado por adaptador |

Cada garantia com prova de sanidade (desligar a regra e ver o teste falhar).
