# ADR-0002: Contrato de frota com dois adaptadores (SimFleet e Fleet UI)

**Status:** aceito (2026-10-26)

## Contexto

O Fleet UI exige ROS 2, Nav2 e Gazebo; o teto validado é de 2 robôs numa máquina
de 8 núcleos com GPU. A VPS do portfólio tem 4 vCPU e nenhuma GPU. O Executor já
fala com o Fleet UI apenas por HTTP.

## Decisão

- A fronteira entre agente e frota é o **contrato de frota**: o subconjunto da
  API HTTP do Fleet UI usado pelo Executor, com os mesmos caminhos, parâmetros e
  formatos de resposta e erro do `fleet-ui@a57a3b1`.
- Dois backends cumprem o contrato:
  - **SimFleet**: serviço próprio deste repositório, 2D, sem ROS.
  - **Fleet UI**: o sistema original, sem alterações.
- O adaptador é escolhido por configuração. O Planner e as ferramentas não sabem
  qual backend está do outro lado.
- Uma suíte de testes de contrato roda contra o SimFleet e contra um fake do
  Fleet UI construído a partir do código de referência.

## Consequências

- Demo pública e testes de ponta a ponta sem ROS.
- Mudanças no contrato exigem conferir o Fleet UI de referência; o SimFleet não
  pode inventar campos que o Fleet UI não tem.
- O SimFleet é cinemático e não substitui o Gazebo como evidência científica. A
  interface pública deve deixar isso claro.
