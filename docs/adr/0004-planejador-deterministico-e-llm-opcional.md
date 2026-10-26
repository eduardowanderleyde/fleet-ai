# ADR-0004: Planejador determinístico por padrão; LLM real opcional e futuro

**Status:** aceito (2026-10-26)
**Altera:** ADR-0003 (o adaptador real de LLM sai da SPEC-001)

## Contexto

A demo pública do Fleet AI não deve depender de APIs pagas de LLM nem de agentes
autônomos consumindo tokens: cada visitante (ou bot) geraria custo para o dono, e
os limites de orçamento só reduzem o prejuízo, não o eliminam. O desenvolvimento
continua com Claude Code e mattpocock-skills, mas o produto precisa funcionar
sem nenhuma chave de API.

## Decisão

- A transformação de instrução em chamadas de ferramenta passa por uma **porta
  de planejador**, com duas implementações:
  - **Planejador determinístico** (padrão e único usado na demo): reconhece um
    conjunto fechado de intenções em português e inglês por regras, monta um
    plano fixo e o executa. Sem modelo de linguagem, sem rede, sem custo.
  - **Planejador LLM** (desligado por padrão): o loop de tool use portado do
    `fleet-ui`, atrás da porta de LLM. Na SPEC-001 só aceita o LLM roteirizado.
- Os dois planejadores compartilham as ferramentas, o despachante, o escopo de
  robô e o formato da missão.
- Nenhum SDK de LLM pago é dependência do projeto na SPEC-001, e nenhuma
  variável de chave de API existe. Um teste garante isso.
- A integração com modelos reais fica para uma spec futura, opcional, que deverá
  trazer junto o orçamento de tokens e custo, o livro de uso e a gestão de chave.
  Ela continuará desligada por padrão.

## Consequências

- Custo de modelo zero na demo pública; as guardas de taxa e concorrência passam
  a proteger CPU e memória, não dinheiro.
- O planejador determinístico entende pouca coisa: só as intenções da tabela. A
  interface precisa mostrar exemplos e tratar `not_understood` com clareza, e não
  deve apresentá-lo como "IA".
- O loop agêntico continua testado (via LLM roteirizado), então ligar um modelo
  real no futuro é escrever um adaptador da porta de LLM, não reestruturar o
  sistema.
