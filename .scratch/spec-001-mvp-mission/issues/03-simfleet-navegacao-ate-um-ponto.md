# 03: SimFleet navega um robô até um destino

**What to build:** `POST /api/go_to_point` aceita o destino de um robô MUUT parado e responde no contrato normalizado (`"Navigation started"`). O SimFleet planeja um caminho A* numa grade de planejamento cuja resolução é um múltiplo inteiro da do mapa (0,09 m no warehouse), derivada de forma conservadora da grade inflada, suaviza o caminho por linha de visada e move o robô a velocidade constante no relógio simulado. O estado de navegação fica `navigating` durante o trajeto e volta a `idle` na chegada, com a pose no destino e o yaw pedido. Nos testes, um relógio manual avança um passo fixo a cada leitura de status, sem esperas reais. Simulação cinemática do MVP, não física fiel (ADR-0005).

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Destino livre e alcançável → `200 {"success": true, "message": "Navigation started", "error_code": ""}` e o robô passa a `navigating`
- [ ] Lendo o status repetidamente com o relógio manual, o robô chega e volta a `idle`, `last_error` vazio, pose final a até 5 cm do destino e yaw igual ao pedido
- [ ] Toda pose observada durante o trajeto está livre na grade inflada da resolução original
- [ ] O caminho contorna obstáculos: entre dois pontos separados por uma parede, a trajetória passa pela abertura, e o tempo de chegada é coerente com o comprimento do contorno, não com a linha reta
- [ ] Caminho suavizado: em área aberta, a trajetória até um destino na diagonal é uma reta (sem "escadinha" de A* 8-conectado)
- [ ] Redução conservadora: um corredor mais estreito que a célula de planejamento, livre na resolução original, não é usado pelo caminho
- [ ] `planning_resolution` no cenário precisa ser múltiplo inteiro da resolução do mapa: 0,09 com mapa de 0,03 carrega; 0,1 com mapa de 0,03 impede o cenário de carregar com `ScenarioError`; sem o campo, usa o múltiplo mais próximo de 0,1 m
- [ ] O warehouse declara `planning_resolution = 0.09`
- [ ] Lugares nomeados são validados ao carregar também na grade de planejamento: um lugar livre na grade inflada original mas bloqueado na grade reduzida impede o cenário de carregar, com mensagem que cita o lugar e a grade
- [ ] Mover um robô não altera a pose dos outros
- [ ] Mesmo cenário e mesma sequência de comandos produzem a mesma sequência de poses
- [ ] `go_to_point` com o robô em `navigating` → `409`, `success: false`, `error_code: ALREADY_NAVIGATING`; o destino em curso não muda
- [ ] `go_to_point` depois da chegada (robô em `idle`) é aceito normalmente
- [ ] `speed_mps` vem do cenário (padrão 0,3 m/s); o fator de escala do relógio vem da configuração do serviço; o warehouse planeja uma rota longa (base → doca de carga) em menos de 1 s

## Testes previstos

Seam: API HTTP do SimFleet em processo, relógio manual injetado. Cenários pequenos desenhados como texto (auxiliar de testes do ticket 02), mais o warehouse.

| Critério | Teste |
|---|---|
| Aceite | `test_go_to_point_starts_navigation` |
| Chegada | `test_robot_arrives_idle_at_destination_with_requested_yaw` |
| Poses livres | `test_every_observed_pose_is_free_on_the_inflated_map` |
| Contorno | `test_path_goes_around_a_wall_through_the_doorway` |
| Suavização | `test_open_area_diagonal_is_a_straight_line` |
| Redução conservadora | `test_corridor_narrower_than_a_planning_cell_is_not_used` |
| Resolução múltipla | `test_planning_resolution_must_be_a_multiple_of_the_map_resolution` (parametrizado: 0,09 aceita, 0,1 recusa, ausente usa o múltiplo mais próximo de 0,1) |
| Warehouse | `test_warehouse_plans_on_a_0_09_m_grid` |
| Lugar nas duas grades | `test_place_blocked_only_on_the_planning_grid_prevents_startup` |
| Isolamento | `test_moving_one_robot_leaves_the_others_still` |
| Determinismo | `test_same_commands_produce_the_same_poses` |
| Já navegando | `test_new_destination_while_navigating_is_rejected` |
| Depois da chegada | `test_new_destination_after_arrival_is_accepted` |
| Configuração e desempenho | `test_speed_comes_from_the_scenario`, `test_warehouse_long_route_plans_in_under_a_second` |
