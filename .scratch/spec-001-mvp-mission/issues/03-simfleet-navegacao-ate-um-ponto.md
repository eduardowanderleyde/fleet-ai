# 03: SimFleet navega um robô até um ponto

**What to build:** `POST /api/go_to_point` aceita o destino de um robô MUUT, planeja um caminho A* sobre a grade com obstáculos inflados e o robô percorre o caminho no relógio simulado. O status mostra `navigating` durante o trajeto e volta a `idle` na chegada, com a pose no destino e o yaw pedido. Em testes, um relógio manual avança um passo fixo a cada leitura de status, sem esperas reais.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Destino livre e alcançável → `{"success": true, ...}` e o robô passa a `navigating`
- [ ] Lendo o status repetidamente com o relógio manual, o robô chega e volta a `idle` com pose final dentro de 5 cm do destino e yaw igual ao pedido
- [ ] O caminho percorrido nunca passa por célula ocupada ou inflada (verificado amostrando as poses observadas)
- [ ] Mover um robô não altera a pose dos outros
- [ ] Mesmo cenário e mesma sequência de comandos produzem a mesma sequência de poses (determinismo)
- [ ] Um novo `go_to_point` durante a navegação substitui o destino anterior
- [ ] Velocidade linear e fator de escala do relógio vêm da configuração
