# Fleet AI

Camada de orquestração por agentes de IA para frotas de robôs móveis. Um agente
(Claude, com tool use) recebe uma missão em linguagem natural e a executa
chamando ferramentas HTTP de alto nível de um **backend de frota**, nunca ROS 2
diretamente.

Derivado da camada de agentes do Fleet UI (`eduardowanderleyde/fleet-ui`), mas
independente dele: os dois só conversam pelo **contrato de frota** HTTP. Ver
`docs/adr/`.

## Regras do projeto

- O repositório `fleet-ui` é só referência de leitura. Não modificar, não fazer
  merge de branches dele; código reaproveitado é copiado e tem a origem
  registrada no commit (ver ADR-0001).
- Spec-Driven Development: todo trabalho parte de uma spec e de tickets em
  `.scratch/`. Implementação com TDD nas seams definidas na spec.
- A suíte padrão de testes nunca chama a API paga da Anthropic: usa o LLM
  roteirizado. Testes com a API real são opt-in e ficam fora da suíte padrão.
- Segredos (como `ANTHROPIC_API_KEY`) só por variável de ambiente; nunca no
  repositório.
- Documentação em português; código, identificadores e mensagens de API em
  inglês.

## Agent skills

### Issue tracker

Specs e tickets são arquivos markdown locais em `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Os cinco papéis canônicos, com o nome padrão (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` e `docs/adr/` na raiz. See `docs/agents/domain.md`.
