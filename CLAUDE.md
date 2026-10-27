# Fleet AI

Orquestração de frotas de robôs móveis a partir de missões em linguagem natural.
Um **planejador** transforma a missão em chamadas de ferramentas HTTP de alto
nível a um **backend de frota**, nunca em comandos ROS 2 diretos. O planejador
padrão é determinístico; o planejador LLM existe, mas fica desligado por padrão
(ADR-0004).

Derivado da camada de agentes do Fleet UI (`eduardowanderleyde/fleet-ui`), mas
independente dele: os dois só conversam pelo **contrato de frota** HTTP. Ver
`docs/adr/`.

## Regras do projeto

- O repositório `fleet-ui` é só referência de leitura. Não modificar, não fazer
  merge de branches dele; código reaproveitado é copiado e tem a origem
  registrada no commit (ver ADR-0001).
- Spec-Driven Development: todo trabalho parte de uma spec e de tickets em
  `.scratch/`. Implementação com TDD nas seams definidas na spec.
- O produto não usa APIs pagas de LLM. Não adicionar SDK de LLM pago como
  dependência, nem variáveis de chave de API, sem uma spec aprovada para isso
  (ADR-0004). O planejador LLM só é testado com o LLM roteirizado.
- O Claude Code é ferramenta de desenvolvimento, não parte do produto.
- Segredos, quando existirem, só por variável de ambiente; nunca no
  repositório.
- Documentação, docstrings, comentários e mensagens de erro de inicialização em
  português; código, identificadores e mensagens da API do Fleet AI em inglês.
  Exceção: as respostas do contrato de frota (SimFleet) reproduzem literalmente
  as do Fleet UI, que são em português (ADR-0002).

## Agent skills

### Issue tracker

Specs e tickets são arquivos markdown locais em `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Os cinco papéis canônicos, com o nome padrão (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` e `docs/adr/` na raiz. See `docs/agents/domain.md`.
