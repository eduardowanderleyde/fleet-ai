# ADR-0007: Modelo local gratuito atrás de configuração explícita

**Status:** aceito (2026-11-02)
**Altera:** ADR-0004 (a integração com modelo real deixa de ser só futura)

## Contexto

O ADR-0004 tirou da SPEC-001 qualquer modelo real para que a demo nunca gerasse
custo para o dono. Com isso, o planejador LLM só rodou com o LLM roteirizado, e
nada mostrava como um modelo de verdade se sai nas mesmas missões. A suíte de
avaliação (SPEC-005, ticket 01) mede isso, mas precisa de um modelo.

A VPS tem 4 vCPUs e 8 GB de RAM, sem GPU. Um modelo pequeno com chamada de
ferramenta (Qwen2.5 3B) roda nela pelo Ollama, que expõe o formato
`/v1/chat/completions` do OpenAI.

## Decisão

- O Fleet AI ganha um adaptador da porta de LLM no formato do OpenAI
  (`FLEET_AI_LLM_ADAPTER=openai_compat`), escrito só com `httpx2`, sem SDK de
  provedor.
- O alvo é um **modelo local e gratuito** (Ollama com `qwen2.5:3b`), no Compose,
  só na rede interna, sem porta publicada e sem chave de API.
- O planejador determinístico continua o padrão. O LLM local só liga com o
  arquivo `compose.llm.yaml` ou com as variáveis `FLEET_AI_PLANNER=llm`,
  `FLEET_AI_LLM_ADAPTER`, `FLEET_AI_LLM_URL` e `FLEET_AI_LLM_MODEL`. Não há troca
  silenciosa entre planejadores.
- O serviço **nunca lê chave de API**. APIs pagas e SDKs de provedor continuam
  fora (o teste de custo zero do ADR-0004 continua valendo). Provedores remotos
  com cota gratuita, se usados, ficam só na suíte de avaliação (SPEC-005,
  ticket 03), fora do serviço.
- Uma chamada ao modelo por vez; um pedido com o modelo ocupado espera até um
  prazo e falha com mensagem fixa.

## Consequências

- Custo de dinheiro continua zero; o custo passa a ser CPU e memória da VPS
  (até 4 GB e 3 CPUs para o Ollama). Uma missão com o modelo leva dezenas de
  segundos, então o tempo máximo da missão sobe para 300 s com o LLM ligado.
- O modelo pequeno erra mais que um grande; as guardas de entrada, a validação
  das chamadas de ferramenta e o escopo de robô continuam valendo para ele, e a
  suíte de avaliação mostra quanto ele erra.
- Exposição pública continua fora: com o LLM ligado, cada missão custa CPU, e
  isso exige controle de acesso e limite de taxa na borda antes de qualquer
  domínio público.
