# ADR-0003: LLM roteirizado na suíte de testes

**Status:** aceito (2026-10-26)

## Contexto

Testar o Planner de ponta a ponta com a API da Anthropic custa dinheiro, depende
de rede e não é determinístico.

## Decisão

- O Planner depende de uma **porta de LLM**, não do SDK diretamente.
- Duas implementações: a real (SDK da Anthropic) e o **LLM roteirizado**, que
  devolve uma sequência fixa de respostas e registra o que recebeu.
- A suíte padrão usa só o LLM roteirizado. Testes contra a API real são opt-in,
  marcados e excluídos por padrão.
- O LLM roteirizado também reporta uso de tokens fictício e configurável, para
  testar orçamento e limites.

## Consequências

- Os testes verificam o comportamento do sistema em torno do modelo
  (despacho, escopo, limites, persistência), não a qualidade das decisões do
  modelo. Avaliar o modelo fica para uma spec própria de avaliação.
