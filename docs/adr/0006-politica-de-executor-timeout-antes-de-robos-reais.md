# ADR-0006: Política de ExecutorTimeout e cancelamento verificado antes de robôs reais

**Status:** proposto (2026-10-27). Não altera a SPEC-001; decidir antes de usar o
adaptador `fleet_ui` com robôs reais.

## Contexto

Hoje há duas formas de uma missão parar por tempo:

- **Tempo máximo da missão** (ticket 08): a navegação em curso enviada pela
  missão é cancelada com verificação, dentro do prazo de confirmação, e a missão
  termina `incomplete` relatando o resultado do cancelamento.
- **`ExecutorTimeout`** (ticket 13): quando o prazo do Executor é menor que o
  tempo restante da missão, a missão termina `incomplete` **sem cancelar**, e o
  texto avisa que o robô pode continuar navegando.

No SimFleet a diferença é inofensiva. Com robôs reais, um robô que continua
navegando depois de uma missão encerrada é um risco operacional.

## Decisão a tomar

Unificar a política: toda parada por tempo, seja do Executor ou da missão, tenta
o mesmo cancelamento verificado da navegação enviada pela missão e relata só o
resultado (`confirmed`, `ambiguous`, `not_confirmed`, falha do backend). Pontos
a decidir:

- se o cancelamento automático depois de `ExecutorTimeout` usa o mesmo prazo de
  confirmação do tempo máximo (5 s);
- como relatar quando o cancelamento falha ou não é confirmado num robô real
  (por exemplo, exigir ação humana);
- se o prazo do Executor deve ser sempre derivado do tempo restante da missão,
  eliminando o `ExecutorTimeout` dentro de missões.

## Consequências esperadas

- O comportamento de parada fica igual para os dois tipos de tempo.
- A SPEC-001 (ticket 13) e o texto de `incomplete` por `ExecutorTimeout` mudam;
  os testes do ticket 13 que exigem "nenhum cancel" precisam ser revistos.
