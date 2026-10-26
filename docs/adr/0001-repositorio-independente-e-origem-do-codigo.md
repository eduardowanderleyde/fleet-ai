# ADR-0001: Repositório independente e origem do código reaproveitado

**Status:** aceito (2026-10-26)

## Contexto

A camada de agentes (Planner, Executor, Analyst) nasceu no `fleet-ui`, que tem
16 branches divergentes. Em 2026-10-22 os agentes saíram do escopo da
dissertação, e a branch mais recente (`new-way-samsung`) esconde o painel de
agentes. Evoluir os agentes dentro do `fleet-ui` misturaria produto e pesquisa.

Comparação das branches em 2026-10-26 (só leitura):

| Branch | Planner / Analyst / ferramentas | Executor |
|---|---|---|
| `feature/multi-robot-orchestration` (`54f882e`) | versão base | sem pose por robô |
| `mission-coordinate-large-scale` | idênticos à base | idêntico à base |
| `new-way-samsung` (`a57a3b1`) | idênticos à base | **corrige a pose por robô** em `get_robot_status` |
| `windows-version` | não tem agentes | não tem |

## Decisão

- O Fleet AI é um repositório próprio, `fleet-ai`.
- **Referência:** `fleet-ui@a57a3b1` (`new-way-samsung`), por ter os mesmos
  Planner, Analyst e ferramentas e o único Executor com a correção multi-robô.
- O código é **copiado e adaptado**, nunca trazido por merge. Cada commit que
  copiar código do `fleet-ui` cita o arquivo e o commit de origem.
- O `fleet-ui` não é modificado.
- Referências futuras, fora da SPEC-001: `windows-version` (alocadores e
  `gridmap`, para a spec de alocação) e `mission-coordinate-large-scale`
  (`MissionRouter`).

## Consequências

- O Fleet AI evolui sem depender do ciclo da dissertação.
- Correções feitas aqui não voltam sozinhas para o `fleet-ui`; isso é aceito.
