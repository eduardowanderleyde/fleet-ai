# ADR-0003: LLM roteirizado na suíte de testes

**Status:** aceito (2026-10-26), alterado pelo ADR-0004

## Contexto

Testar o loop de tool use de ponta a ponta com uma API de LLM custa dinheiro,
depende de rede e não é determinístico.

## Decisão

- O planejador LLM depende de uma **porta de LLM**, não de um SDK diretamente.
- O **LLM roteirizado** implementa essa porta: devolve uma sequência fixa de
  respostas (texto e `tool_use`), registra o que recebeu e falha alto se o
  roteiro acabar. Também reporta uso de tokens fictício e configurável.
- Toda a suíte de testes usa só o LLM roteirizado.
- ~~Uma implementação real (SDK da Anthropic) existe ao lado, com testes
  opt-in.~~ Alterado pelo ADR-0004: na SPEC-001 não há implementação real; ela
  fica para uma spec futura, opcional e desligada por padrão.

## Consequências

- Os testes verificam o comportamento do sistema em torno do modelo
  (despacho, escopo, limite de turnos, formato da missão), não a qualidade das
  decisões de um modelo. Avaliar modelos fica para a spec de integração real.
