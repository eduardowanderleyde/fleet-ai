# SPEC-005: LLM gratuito e suíte de avaliação

**Status:** ready-for-agent
**Aprovada em:** 2026-11-02
**Decisões relacionadas:** ADR-0003, ADR-0004 (a ser alterado por um ADR-0007 no ticket 02), ADR-0006
**Depende de:** SPEC-001 concluída (tickets 01 a 15); Compose local (ticket 12)

## Problem Statement

O planejador LLM existe e está testado, mas só com o LLM roteirizado: nenhum
modelo de verdade nunca planejou uma missão. Para um projeto de engenharia de
IA, isso deixa a parte mais importante sem prova. Também não há como medir se
um planejador acerta: os testes garantem contratos e segurança, não a taxa de
acerto em instruções variadas, ambíguas, impossíveis ou maliciosas.

O ADR-0004 continua valendo no essencial: nenhuma API paga, nenhum custo para
o dono e nada que um visitante consiga transformar em gasto.

## Solution

1. Uma **suíte de avaliação** com instruções em português (e algumas em
   inglês), cada uma com o resultado esperado verificado por regras, nunca por
   outro LLM. Ela roda contra qualquer planejador e gera uma tabela com
   acerto, recusas corretas, chamadas de ferramenta inválidas, latência e
   custo.
2. Um **adaptador de LLM compatível com a API do OpenAI** (`/v1/chat/completions`
   com ferramentas), usado primeiro com um **modelo local no Ollama**, dentro
   do Compose e na rede interna. É grátis, sem chave e sem enviar dados para
   fora da VPS.
3. **Provedores remotos com cota gratuita** (Groq, OpenRouter, GitHub Models),
   pelo mesmo adaptador, **só na suíte de avaliação**: o serviço nunca lê
   chave de API.

O planejador determinístico continua o padrão. O planejador LLM só roda com
configuração explícita, nunca há troca silenciosa de um para o outro.

## Fora do escopo

- APIs pagas (Anthropic, OpenAI pago) e qualquer SDK de provedor.
- LLM como juiz na avaliação.
- Exposição pública, domínio, HTTPS, autenticação.
- Mudanças na interface web além de mostrar o planejador e o modelo em uso.
- Missões com várias ações (SPEC-002) e servidor MCP (SPEC-004).

## Tickets

| # | Ticket | Bloqueado por |
|---|---|---|
| 01 | Suíte de avaliação de planejadores | — |
| 02 | Adaptador compatível com OpenAI e modelo local no Ollama | 01 |
| 03 | Provedores remotos gratuitos na suíte de avaliação | 01, 02 |

## Decisões (2026-11-02)

1. **Modelo padrão local:** `qwen2.5:3b` (~2 GB, chamada de ferramenta
   razoável, rápido o bastante na CPU da VPS).
2. **Download do modelo:** a rede interna não tem saída para a internet. Um
   serviço de uso único (`ollama-pull`, perfil `setup`) na rede `edge` baixa o
   modelo para o volume e sai; o `ollama` de execução fica só na rede interna.
3. **Demo na VPS:** o determinístico continua o padrão; o LLM local é ligado só
   por configuração explícita (`compose.llm.yaml`).
4. **Tamanho da suíte:** ~50 casos em categorias fixas.
