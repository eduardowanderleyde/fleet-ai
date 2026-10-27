# ADR-0002: Contrato de frota com dois adaptadores (SimFleet e Fleet UI)

**Status:** aceito (2026-10-26), alterado pelo ADR-0005

## Contexto

O Fleet UI exige ROS 2, Nav2 e Gazebo; o teto validado é de 2 robôs numa máquina
de 8 núcleos com GPU. A VPS do portfólio tem 4 vCPU e nenhuma GPU. O Executor já
fala com o Fleet UI apenas por HTTP.

## Decisão

- A fronteira entre agente e frota é o **contrato de frota**: o subconjunto da
  API HTTP do Fleet UI usado pelo Executor, com os mesmos caminhos e parâmetros
  do `fleet-ui@a57a3b1`. ~~Os mesmos formatos de resposta e erro.~~ Alterado
  pelo ADR-0005: as respostas de comando são normalizadas (`success`, `message`,
  `error_code`), e a tradução do formato bruto do Fleet UI fica no adaptador
  `fleet_ui`.
- Dois backends cumprem o contrato:
  - **SimFleet**: serviço próprio deste repositório, 2D, sem ROS.
  - **Fleet UI**: o sistema original, sem alterações.
- O adaptador é escolhido por configuração. O Planner e as ferramentas não sabem
  qual backend está do outro lado.
- Uma suíte de testes de contrato roda pelo Executor contra o SimFleet e contra
  um fake do Fleet UI que emite as respostas brutas do código de referência.

## Consequências

- Demo pública e testes de ponta a ponta sem ROS.
- Mudanças no contrato exigem conferir o Fleet UI de referência: todo campo ou
  código do contrato precisa ter correspondente no Fleet UI, ou uma tradução
  definida no adaptador `fleet_ui` (ADR-0005).
- O SimFleet é cinemático e não substitui o Gazebo como evidência científica. A
  interface pública deve deixar isso claro.
