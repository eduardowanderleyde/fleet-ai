# 02: SimFleet carrega um cenário e responde lista de robôs e status

**What to build:** O SimFleet sobe a partir de um cenário (mapa de ocupação, resolução, origem, raio de inflação e robôs com papel e pose inicial) e responde `GET /api/list_robots` e `GET /api/status` exatamente no formato do contrato de frota. O cenário padrão é o warehouse do `fleet-ui`, com dois robôs MUUT e um FUUT. Ainda não há movimento.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] `GET /api/list_robots` devolve `{"robot_ids": [...]}` com os robôs do cenário, na ordem do cenário
- [ ] `GET /api/status` devolve `robots` (com `robot_id`, `role`, `nav_state`, `current_route`, `collection_on`, `collection_file`, `last_error`, `bytes_written`), `pose` (do primeiro robô) e `poses` por robô com `x`, `y`, `yaw`, `valid: true`
- [ ] Todo robô começa em `nav_state: "idle"` na pose inicial do cenário
- [ ] O mapa e os parâmetros do warehouse vêm do `fleet-ui` com a origem (arquivo e commit) registrada
- [ ] Cenário inválido (imagem ausente, robô começando em célula ocupada, id duplicado) impede o serviço de subir, com mensagem clara
- [ ] O cenário é escolhido por configuração; os testes usam um cenário pequeno próprio, além do warehouse
