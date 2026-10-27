# 02: SimFleet carrega um cenário e responde lista de robôs e status

**What to build:** O SimFleet sobe a partir de um cenário (mapa de ocupação, resolução, origem, raio de inflação, robôs com papel, apelidos e pose inicial, e lugares nomeados) e responde `GET /api/list_robots` e `GET /api/status` exatamente no formato do contrato de frota. O cenário padrão é o warehouse do `fleet-ui`, com dois robôs MUUT, um FUUT e ao menos 5 lugares nomeados. Ainda não há movimento.

**Blocked by:** 01

**Status:** resolved

- [x] `GET /api/list_robots` devolve `{"robot_ids": [...]}` com os robôs do cenário, na ordem do cenário
- [x] `GET /api/status` devolve `robots` (com `robot_id`, `role`, `nav_state`, `current_route`, `collection_on`, `collection_file`, `last_error`, `bytes_written`), `pose` (do primeiro robô) e `poses` por robô com `x`, `y`, `yaw`, `valid: true`
- [x] Todo robô começa em `nav_state: "idle"` na pose inicial do cenário
- [x] Apelidos de robôs e lugares nomeados (nome, sinônimos PT/EN, x, y, yaw) são lidos do cenário, mas não aparecem nas respostas do contrato
- [x] O mapa e os parâmetros do warehouse vêm do `fleet-ui`, com a origem (arquivo e commit) registrada
- [x] Cenário inválido (imagem ausente, robô ou lugar em célula ocupada, id ou nome duplicado, apelido igual entre dois robôs) impede o serviço de subir, com mensagem clara
- [x] O cenário é escolhido por configuração; os testes usam um cenário pequeno próprio, além do warehouse
