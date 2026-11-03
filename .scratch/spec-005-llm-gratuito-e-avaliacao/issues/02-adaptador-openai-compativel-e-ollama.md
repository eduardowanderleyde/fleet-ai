# 02: Adaptador compatível com OpenAI e modelo local no Ollama

**What to build:** Uma segunda implementação da porta de LLM que fala o formato `/v1/chat/completions` com ferramentas, convertendo de e para os blocos da porta (`TextBlock`, `ToolUseBlock`, `tool_result`). O primeiro alvo é o Ollama, que expõe esse formato: um serviço `ollama` entra no Compose, só na rede interna, sem porta publicada e sem chave. Com `FLEET_AI_PLANNER=llm` e `FLEET_AI_LLM_ADAPTER=openai_compat`, uma missão real é planejada pelo modelo local. O padrão continua o determinístico.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] ADR-0007 altera o ADR-0004: modelo local gratuito permitido atrás de configuração explícita; APIs pagas e SDKs de provedor continuam fora; o serviço nunca lê chave de API
- [ ] `OpenAICompatLlm` implementa `LlmPort` só com `httpx2` (sem SDK): sistema vira mensagem `system`; ferramentas viram `tools` com `function.parameters`; `tool_calls` da resposta viram `ToolUseBlock`; `finish_reason` `stop`/`tool_calls`/`length` viram `end_turn`/`tool_use`/`max_tokens`; outro valor ou JSON de argumentos inválido → `InvalidLlmResponse` (missão `failed`, como hoje)
- [ ] Configuração validada na inicialização, sem rede: `FLEET_AI_LLM_URL` (mesmas regras da URL da frota: sem credenciais, query ou fragmento), `FLEET_AI_LLM_MODEL`, `FLEET_AI_LLM_TIMEOUT_S`; qualquer variável `*_API_KEY` é ignorada pelo serviço
- [ ] Erro de rede, timeout, status diferente de 200 ou corpo grande demais (limite de bytes) → exceção da porta, missão `failed` com mensagem fixa; URL, corpo e texto do provedor só no log, nunca na missão nem no `/health`
- [ ] No máximo 1 chamada ao LLM em andamento por vez (CPU da VPS); um pedido com o LLM ocupado espera até o limite e depois falha com mensagem fixa, sem fila sem fim
- [ ] Uso de tokens real (`usage.prompt_tokens`/`completion_tokens`) registrado na missão e somado no relatório da avaliação
- [ ] `/health`: `planner: "llm"`, `llm_enabled: true` e `llm_model` (nome do modelo, nunca URL); a readiness não chama o modelo
- [ ] Compose: serviço `ollama` com imagem de versão fixa, só na rede `internal`, sem `ports`, volume nomeado para os modelos, limite de memória (4 GB para `qwen2.5:3b`), healthcheck; serviço de uso único `ollama-pull` no perfil `setup`, na rede `edge`, que baixa o modelo e sai
- [ ] `FLEET_AI_PLANNER` continua `deterministic` no `compose.yaml`; o LLM local é ligado por um arquivo de override documentado (`compose.llm.yaml`), sem chave
- [ ] Suíte do ticket 01 rodada contra `qwen2.5:3b` na VPS; resultado no README ao lado da linha de base, com modelo, versão do Ollama, data e commit
- [ ] Interface web mostra o planejador e o modelo em uso (do `/health`), sem outra mudança

## Testes previstos

Seam: `OpenAICompatLlm` contra um servidor falso em processo (`httpx2.MockTransport`) que registra o pedido e devolve respostas no formato do OpenAI; o planejador LLM e a API HTTP do Fleet AI com esse adaptador e o SimFleet em processo. Nenhum teste automático chama o Ollama de verdade; a execução real fica num roteiro manual (`scripts/ollama-smoke.sh`).

| Garantia | Teste |
|---|---|
| Conversão do pedido | `test_request_carries_system_tools_and_tool_results_in_openai_format` |
| Conversão da resposta | `test_tool_calls_and_finish_reasons_map_to_port_blocks` (parametrizado) |
| Resposta inválida | `test_malformed_arguments_or_unknown_finish_reason_fail_the_mission` |
| Missão completa | `test_openai_compat_mission_completes_with_the_fake_server` |
| Erros sem vazamento | `test_provider_errors_fail_with_a_fixed_message` (timeout, 500, corpo grande, texto bruto do provedor nunca na missão) |
| Concorrência | `test_only_one_llm_call_runs_at_a_time` |
| Configuração | `test_llm_configuration` (URL inválida, modelo ausente, adaptador desconhecido → `ValueError` na inicialização; nenhuma chave lida) |
| Health | `test_health_reports_model_name_without_url` |
| Compose | `test_ollama_is_internal_unpublished_and_pinned` (estático, como `tests/test_compose.py`) |
