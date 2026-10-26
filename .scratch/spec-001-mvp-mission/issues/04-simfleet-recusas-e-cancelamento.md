# 04: SimFleet recusa comandos inválidos e cancela navegação

**What to build:** O SimFleet se comporta como o Fleet UI nos casos de erro: robô de papel diferente de MUUT recebe 403 com a mesma mensagem do Fleet UI; destino em célula ocupada, fora do mapa ou sem caminho é recusado com `success: false` e o robô fica em `failed` com `last_error`; `POST /api/cancel` interrompe a navegação e deixa o robô parado onde está.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] `go_to_point` para robô FUUT ou SU → HTTP 403 com `{"success": false, "message": "<robot_id>: papel '<role>' não permite movimento"}`; a pose não muda
- [ ] `go_to_point` para robô inexistente → HTTP 403 com `"<robot_id>: robot_id não declarado em roles.yaml"`, como no Fleet UI de referência
- [ ] Destino ocupado, fora do mapa ou sem caminho → HTTP 200 com `success: false` e mensagem distinta para cada caso; robô em `failed` com `last_error` preenchido
- [ ] Um `go_to_point` válido depois de `failed` volta a funcionar normalmente
- [ ] `cancel` durante a navegação → `success: true`, robô em `idle` na pose em que estava; poses seguintes não mudam
- [ ] `cancel` com o robô parado → `success: true` sem efeito colateral
