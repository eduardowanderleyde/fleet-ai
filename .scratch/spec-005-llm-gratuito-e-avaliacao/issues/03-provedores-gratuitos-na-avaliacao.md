# 03: Provedores remotos gratuitos na suíte de avaliação

**What to build:** A suíte de avaliação ganha provedores remotos com cota gratuita (Groq, OpenRouter com modelos `:free`, GitHub Models), pelo mesmo `OpenAICompatLlm` do ticket 02, para comparar o modelo local com modelos maiores. A chave de API é lida só pelo executor da avaliação, de um arquivo local que o dono edita; o serviço Fleet AI e o Compose continuam sem chave. Antes de implementar, conferir nas páginas oficiais os limites e a política de uso de dados de cada provedor, e registrar a data da consulta.

**Blocked by:** 01, 02

**Status:** ready-for-agent

- [ ] Provedores numa lista fechada em `fleet_eval` (nome, URL base `https`, variável da chave); URL fora da lista é recusada
- [ ] Chave lida só de `.env.eval` (já ignorado pelo `.gitignore` e pelo `.dockerignore` via `.env*`) ou do ambiente, pelo executor da avaliação; nunca pelo pacote `fleet_ai`
- [ ] A chave nunca aparece em saída, log, relatório JSON, exceção ou `repr`; erros do provedor são resumidos por status e tipo
- [ ] Respeito à cota: limite de pedidos por minuto configurável por provedor, `429` com espera pelo `Retry-After` (com teto) e no máximo 2 novas tentativas; ao estourar a cota do dia, a suíte para e marca os casos restantes como `nao_executado`, sem contar como erro do modelo
- [ ] `--max-requests` obrigatório para provedores remotos: a suíte nunca faz mais pedidos do que o informado
- [ ] Custo registrado como zero só para modelos marcados como gratuitos na lista; outro modelo é recusado (nada de cobrança por engano)
- [ ] Relatório comparativo em Markdown: determinístico, modelo local e cada provedor remoto, por categoria, com modelo, data e commit; tabela final no README
- [ ] README explica que os provedores remotos são opcionais, só para avaliação, e que o plano gratuito de alguns pode usar os dados enviados (a suíte só envia instruções fictícias do armazém)

## Testes previstos

Seam: o executor da avaliação com um servidor falso do provedor em processo (`httpx2.MockTransport`), que registra pedidos e cabeçalhos. Nenhum teste automático usa a internet nem uma chave real.

| Garantia | Teste |
|---|---|
| Chave só no executor | `test_fleet_ai_never_reads_api_keys` (atualiza o teste de custo zero do ticket 10 para valer só para `fleet_ai`) |
| Chave nunca vaza | `test_api_key_never_appears_in_output_logs_or_report` (chave de teste com marcador; procura em stdout, logs, JSON e exceções) |
| Provedor fora da lista | `test_unknown_provider_or_non_free_model_is_refused` |
| Cota | `test_rate_limit_waits_retry_after_and_stops_at_the_daily_quota` |
| Teto de pedidos | `test_suite_never_exceeds_max_requests` |
| Relatório | `test_comparative_report_lists_each_planner_by_category` |
