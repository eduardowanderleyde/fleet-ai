# 10: Adaptador real da Anthropic e configuração do LLM

**What to build:** A porta de LLM ganha a implementação real com o SDK da Anthropic. Modelo, chave, limite de tokens por chamada e adaptador (`anthropic` ou `scripted`) vêm do ambiente. O serviço falha cedo se o adaptador real estiver ativo sem chave, e a chave nunca aparece em logs, respostas ou mensagens de erro. Um teste de fumaça opt-in roda uma missão curta contra a API real.

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] Adaptador real converte entre a porta de LLM e o SDK, incluindo `tool_use`, `tool_result` com `is_error` e uso de tokens
- [ ] Modelo recomendado confirmado contra a documentação atual da API antes de virar padrão do exemplo de configuração
- [ ] Adaptador `anthropic` sem chave → o serviço não sobe, com mensagem que não ecoa nenhum valor de ambiente
- [ ] Teste garante que a chave configurada não aparece em logs nem no corpo de nenhuma resposta, inclusive em erros do SDK
- [ ] Erro da API (ex.: 429 ou 5xx do provedor) → missão `failed` com mensagem genérica, sem detalhes internos
- [ ] Teste de fumaça marcado opt-in, fora da suíte padrão, documentado no README com o custo esperado
- [ ] Arquivo de exemplo de ambiente sem segredos, listando todas as variáveis
