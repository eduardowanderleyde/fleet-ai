# SPEC-001: MVP — missão em linguagem natural contra o SimFleet, sem LLM pago

**Status:** ready-for-agent
**Aprovada em:** 2026-10-26 (revisada no mesmo dia: sem APIs pagas, ADR-0004; contrato normalizado e navegação assíncrona, ADR-0005)
**Referência de código:** `fleet-ui@a57a3b1` (ver ADR-0001)
**Decisões relacionadas:** ADR-0001, ADR-0002, ADR-0003, ADR-0004, ADR-0005
**Revisões:** 2026-10-27, encerramento garantido de missões (ticket 13); conflito de escopo no planejador determinístico (ticket 09); retenção segura e limpeza do limitador de taxa (ticket 14)

## Problem Statement

Os agentes do Fleet UI só funcionam com ROS 2, Nav2 e Gazebo rodando numa
máquina de desenvolvimento potente, e cada instrução consome tokens de uma API
paga. Por isso não dá para demonstrá-los publicamente sem custo, nem testá-los
de ponta a ponta sem a simulação completa. Uma demo pública que chame um LLM
pago é também um alvo de abuso: qualquer visitante gasta o dinheiro do dono.

## Solution

O Fleet AI é um serviço independente que recebe uma **missão** em linguagem
natural (português ou inglês) e a executa chamando **ferramentas** de alto
nível de um **backend de frota**, pelo **contrato de frota** HTTP. Há dois
backends intercambiáveis: o **SimFleet** (2D, sem ROS, roda em qualquer
máquina) e o **Fleet UI** original.

Quem transforma a instrução em chamadas de ferramenta é um **planejador**. O
padrão, e o único usado na demo pública, é o **planejador determinístico**: ele
reconhece um conjunto fechado de **intenções** (listar robôs, consultar estado,
mover até um **lugar nomeado** ou coordenada, cancelar) por regras, sem nenhum
modelo de linguagem e sem custo. O **planejador LLM** (o loop de tool use
portado do `fleet-ui`) também existe, atrás de uma **porta de LLM**, mas na
SPEC-001 só roda com o **LLM roteirizado**, fica desligado por padrão e serve
para manter o caminho pronto para uma integração futura e opcional com modelos
reais.

O sistema inteiro sobe e passa nos testes **sem nenhuma chave de API**.

## User Stories

1. Como visitante da demo, quero escrever "leve o tb1 até a doca de carga" e receber um identificador de missão, para acompanhar a execução.
2. Como visitante, quero escrever a mesma missão em inglês ("move tb1 to the loading dock") e obter o mesmo resultado, com a resposta em inglês.
3. Como visitante, quero mandar um robô para coordenadas ("mova o tb2 para x 3,5 y -1"), para explorar o mapa livremente.
4. Como visitante, quero perguntar "onde está o tb1?" ou "liste os robôs", para conhecer a frota antes de dar ordens.
5. Como visitante, quero cancelar a navegação de um robô ("pare o tb1"), para interromper uma missão.
6. Como visitante, quero consultar a missão e ver o status (`running`, `completed`, `not_understood`, `incomplete`, `failed`, `rejected`), para saber se ela terminou.
7. Como visitante, quero ver cada passo executado, com a entrada e o resultado, para entender como a missão foi cumprida.
8. Como visitante, quero um texto final resumindo o que foi feito, com a pose final do robô quando houver movimento.
9. Como visitante, quero que uma instrução fora das intenções suportadas termine como `not_understood` com exemplos do que posso pedir, em vez de um erro genérico.
10. Como visitante, quero que pedir um robô inexistente, um lugar desconhecido ou um destino dentro de uma parede gere uma explicação clara.
10a. Como visitante, quero que mandar um robô que já está navegando para outro destino seja recusado com a sugestão de cancelar antes, para não perder o controle do que ele está fazendo.
11. Como visitante, quero que pedir movimento a um robô de papel FUUT ou SU seja recusado com o motivo, como no Fleet UI.
12. Como visitante, quero referir-me aos robôs pelo id ("tb1") ou por apelidos do cenário ("robô 1", "robot one"), e aos lugares por nome ou sinônimo, sem me preocupar com maiúsculas ou acentos.
13. Como dono, quero que a demo funcione sem nenhuma chave de API e sem nenhuma dependência de SDK de LLM pago, para ter custo zero de modelo.
14. Como dono, quero que o planejador LLM fique desligado por padrão e só possa ser ligado por configuração explícita, para que ninguém o ative por engano.
15. Como dono, quero que instruções acima do tamanho máximo sejam rejeitadas antes de qualquer planejamento.
16. Como dono, quero limitar quantas missões um mesmo IP pode criar por minuto e por dia, para conter bots que esgotariam CPU e memória.
17. Como dono, quero limitar quantas missões rodam ao mesmo tempo e quanto tempo cada uma pode durar.
18. Como pesquisador, quero apontar o Fleet AI para o Fleet UI real só trocando a configuração do adaptador de frota.
19. Como pesquisador, quero restringir uma missão a um único robô, de forma estrutural, para que nenhuma instrução comande outro robô.
19a. Como visitante, quero que uma instrução que cita um robô diferente do escopo da missão seja recusada com a explicação do conflito, em vez de executada silenciosamente no robô do escopo, para que a ação nunca divirja do que eu pedi.
20. Como pesquisador, quero que o SimFleet carregue um cenário (mapa, resolução, origem, robôs com papel, apelidos e pose inicial, e lugares nomeados), para reproduzir o ambiente do warehouse.
21. Como pesquisador, quero que a mesma instrução no mesmo cenário produza sempre o mesmo plano e as mesmas poses, para depurar e comparar.
22. Como desenvolvedor, quero testar as intenções do planejador determinístico com uma tabela de casos (instrução → plano esperado) em português e inglês.
23. Como desenvolvedor, quero testar o loop do planejador LLM de ponta a ponta com o LLM roteirizado, sem rede e sem custo, para que a integração futura com um modelo real seja só um novo adaptador.
24. Como desenvolvedor, quero que os dois planejadores usem as mesmas ferramentas, o mesmo escopo de robô e o mesmo registro de passos, para que a missão tenha o mesmo formato independentemente do planejador.
25. Como desenvolvedor, quero uma suíte de testes de contrato que rode contra o SimFleet e contra o fake do Fleet UI, este emitindo as respostas brutas reais do Fleet UI, para provar que o adaptador `fleet_ui` as normaliza.
25a. Como operador, quero a causa detalhada de cada navegação falhada (destino ocupado, fora do mapa, sem caminho) num log estruturado do SimFleet, já que o contrato só carrega o código de erro.
26. Como desenvolvedor, quero que, no planejador LLM, o limite de turnos termine a missão como `incomplete` com os passos preservados.
27. Como operador, quero endpoints de health nos dois serviços, informando o adaptador de frota, se o backend responde e o planejador ativo.
28. Como operador, quero subir Fleet AI e SimFleet localmente com Docker Compose, com o SimFleet sem porta publicada.
29. Como operador, quero logs estruturados com `mission_id`.

## Implementation Decisions

### Módulos

- **Serviço Fleet AI (FastAPI):** API pública de missões, executor de missões, planejadores, ferramentas, Executor, guardas e configuração.
- **Serviço SimFleet (FastAPI):** implementa o contrato de frota sobre um cenário. Processo e imagem próprios.
- **Executor e adaptadores de frota:** o Executor é portado do `fleet-ui`, com a correção de pose por robô, mais duas operações compostas: aguardar o fim da navegação e cancelar com verificação (ambas por polling do status, com intervalo e timeout configuráveis). O Executor lembra, por robô, o destino ativo que ele mesmo enviou, para correlacionar cancelamentos (ADR-0005). Ele fala o contrato normalizado. O adaptador `sim` repassa as respostas do SimFleet; o adaptador `fleet_ui` é o **único** lugar que traduz as respostas brutas do Fleet UI para o contrato (ADR-0005). Falhas de comando chegam aos planejadores como erro com `error_code`.
- **Ferramentas e despachante:** um único despachante recebe `(nome da ferramenta, entrada)`, aplica o escopo de robô, chama o Executor e devolve o resultado ou o erro. Os dois planejadores usam o mesmo despachante.
- **Porta de planejador:** recebe a instrução, o escopo de robô opcional e o despachante; devolve status, passos e texto final. Duas implementações:
  - **Planejador determinístico** (padrão): normaliza o texto, reconhece uma intenção e seus argumentos por regras, monta um plano fixo de chamadas e o executa pelo despachante.
  - **Planejador LLM** (desligado por padrão): o loop de tool use do `fleet-ui`, portado para depender da porta de LLM.
- **Porta de LLM:** recebe sistema, mensagens, ferramentas e limite de tokens; devolve blocos de conteúdo, motivo de parada e uso. Na SPEC-001 há uma única implementação, o **LLM roteirizado**.

### Planejador determinístico

- **Normalização:** minúsculas, sem acentos, espaços colapsados, vírgula decimal aceita ("3,5").
- **Idioma:** detectado pelas palavras da instrução (português ou inglês); empate ou indefinido usa inglês. O texto final sai no idioma detectado.
- **Intenções do MVP** (uma por missão):

| Intenção | Exemplos | Plano |
|---|---|---|
| Listar robôs | "liste os robôs", "which robots are there" | `list_robots` |
| Estado de um robô | "onde está o tb1?", "status of robot 2" | `get_robot_status` |
| Mover até lugar nomeado | "leve o tb1 até a doca de carga", "send tb2 to the north shelf" | `get_robot_status` → `move_robot` → `wait_for_arrival` |
| Mover até coordenada | "mova o tb1 para x 3,5 y -1", "move tb1 to (2, 4) facing 90" | `get_robot_status` → `move_robot` → `wait_for_arrival` |
| Cancelar | "pare o tb1", "cancel tb2" | `cancel_navigation` |

- **Referências:** robôs pelo id ou por apelidos do cenário; lugares por nome ou sinônimos do cenário, em português e inglês. O yaw é opcional, em graus na instrução e radianos no contrato.
- **Formas de coordenada** (ticket 07): `x 3,5 y -1` ou `x=3.5 y=-1` (vírgula ou ponto decimal); `(1; 2,5)` (ponto e vírgula separa, vírgula decimal aceita); `(2, 4)` e `to 2.0, 4.0` / `para 2.0, 4.0` (vírgula separa, só ponto decimal). Por isso `(2,5)` é x = 2, y = 5; para decimal com vírgula, use `;`. O yaw vem depois de "facing", "heading", "yaw", "virado para" ou "orientação", em graus.
- **Não entendido:** sem intenção reconhecida, robô ausente quando a intenção exige um, ou mais de uma intenção na mesma instrução → status `not_understood`, sem chamar nenhuma ferramenta, com 3 exemplos de instruções válidas no idioma detectado.
- **Lugar ou robô desconhecido:** `not_understood` com a lista de nomes válidos do cenário.
- **Falha de comando** (robô desconhecido, papel sem movimento, robô já navegando): o plano para no passo que falhou e a missão termina `completed` com o texto final explicando a falha pelo `error_code`; para `ALREADY_NAVIGATING`, o texto sugere cancelar antes ("pare o tb1"). O planejador nunca cancela sozinho para enviar outro destino.
- **Falha de navegação** (destino inválido ou abortado): o `move_robot` é aceito e a falha aparece no resultado do `wait_for_arrival` (`nav_state: failed`, `last_error`); a missão termina `completed` com o texto final explicando a falha.
- Em todos os casos a missão foi entendida e executada até onde o backend permitiu; por isso o status é `completed`, e o sucesso ou a falha da ação ficam no texto final e nos passos.
- **Cancelar:** o texto final reflete o resultado do cancelamento; só diz que a navegação foi cancelada com `confirmed`. Com `ambiguous`, diz que o robô parou mas que não é possível afirmar que foi pelo cancelamento; com `not_confirmed`, diz que o robô continua navegando.
- **Conflito de escopo** (ticket 09): numa missão com `robot_id` de escopo, se a instrução cita explicitamente **outro** robô (pelo id, por um apelido de outro robô do cenário ou por uma referência com cara de robô fora do cenário, como "tb9"), o planejador determinístico recusa com `not_understood`, explica o conflito (robô citado × robô do escopo) e não chama nenhuma ferramenta. Se a instrução cita o próprio robô do escopo (por id ou apelido), ou não cita robô nenhum, a missão segue com o robô do escopo. A reescrita estrutural do `robot_id` no despachante continua valendo para qualquer planejador: o conflito é uma recusa a mais do planejador determinístico, não substitui a garantia do despachante. O escopo vale só dentro da missão: a ferramenta `list_robots` e os endpoints de leitura da frota no backend (`/api/status`, `/api/list_robots`) não são restritos por ele.
- O planejador determinístico não faz chamadas de rede além do despachante e não tem aleatoriedade.

### Planejador LLM (desligado por padrão)

- Mantém as regras de sistema do `fleet-ui` (nunca inventar robôs ou valores, conferir estado antes de mover, resumir no fim) e acrescenta "aguardar a chegada antes de declarar sucesso" e "responder no idioma da instrução".
- Limite de turnos e de tokens de saída por chamada, configuráveis; ao atingir o limite de turnos, a missão termina `incomplete` com os passos preservados.
- Erro de ferramenta volta ao modelo como resultado de erro.
- Só é ativado com configuração explícita do planejador `llm`. Na SPEC-001, o único adaptador de LLM aceito é o roteirizado; qualquer outro valor impede o serviço de subir.

### Ferramentas do MVP

| Ferramenta | Contrato de frota |
|---|---|
| `list_robots` | `GET /api/list_robots` |
| `get_robot_status` | `GET /api/status` (filtra o robô; pose de `poses[robot_id]`) |
| `move_robot` | `POST /api/go_to_point` |
| `wait_for_arrival` | polling de `GET /api/status` até o estado de navegação sair de `navigating`; devolve estado final, `last_error` e pose |
| `cancel_navigation` | `POST /api/cancel` e, se aceito, polling até o estado sair de `navigating`; devolve o resultado `confirmed`, `ambiguous` ou `not_confirmed` |

As demais ferramentas do `fleet-ui` (gravação, replay, coleta, experimentos, campanhas, Analyst) não entram na SPEC-001.

### Contrato de frota (normalizado, ver ADR-0005)

Mesmos caminhos e parâmetros do `fleet-ui@a57a3b1`. Consultas sem mudança de formato; comandos com resposta normalizada `{"success": bool, "message": str, "error_code": str}`. `message` é texto legível em inglês, só para pessoas; clientes decidem pelo `error_code`.

- `GET /api/list_robots` → `{"robot_ids": [...]}`
- `GET /api/status` → `{"robots": [{"robot_id", "role", "nav_state", "current_route", "collection_on", "collection_file", "last_error", "bytes_written"}], "pose": {...}, "poses": {robot_id: {"x", "y", "yaw", "valid"}}}`
- `POST /api/go_to_point?robot_id&x&y&yaw` → aceito: `200 {"success": true, "message": "Navigation started", "error_code": ""}`.
- `POST /api/cancel?robot_id` → aceito: `200 {"success": true, "message": "Cancel requested", "error_code": ""}`, e o robô passa a `idle` na pose em que estava.
- Estado de navegação (`nav_state`): `idle`, `navigating`, `failed`. Na chegada: `idle` e `last_error` vazio.
- **Navegação assíncrona:** um destino bem formado é sempre aceito; falhas de planejamento aparecem na leitura seguinte do status como `failed` com `last_error: NAV2_REJECTED`. `NAV2_ABORTED` fica para falhas durante a execução (o SimFleet do MVP não as produz).
- **Novo destino:** só é aceito com o robô fora de `navigating` (senão `ALREADY_NAVIGATING`).
- **Resultado do cancelamento** (decidido no Executor, por correlação, ADR-0005): `confirmed` só quando este Executor enviou o destino ativo do robô e o viu em `navigating`, o `cancel` foi aceito e a primeira leitura seguinte mostra `idle`; `ambiguous` quando o `cancel` foi aceito mas o robô aparece em `failed` (por exemplo, `NAV2_ABORTED`) ou o destino ativo não veio deste Executor; `not_confirmed` quando o robô continua em `navigating` até o timeout. `NAV2_ABORTED` nunca é, sozinho, evidência de cancelamento.
- **Limitação do Fleet UI:** o status não tem id de objetivo, e outros clientes podem enviar destinos ao mesmo robô; a correlação é por robô e pela ordem dos eventos observados pelo Executor. Por isso `ambiguous` é um resultado legítimo.

| `error_code` | Quando | HTTP | Onde aparece |
|---|---|---|---|
| `INVALID_REQUEST` | `x`, `y` ou `yaw` ausente, não numérico, infinito ou NaN; `robot_id` ausente | 422 | resposta |
| `UNKNOWN_ROBOT` | robô fora do cenário | 403 | resposta |
| `ROLE_NOT_ALLOWED` | `go_to_point` para robô de papel diferente de MUUT | 403 | resposta |
| `ALREADY_NAVIGATING` | `go_to_point` com o robô em `navigating` | 409 | resposta |
| `CANCEL_FAILED` | `cancel` sem navegação ativa | 409 | resposta |
| `NAV2_REJECTED` | destino ocupado ou próximo demais de obstáculo, fora do mapa, ou sem caminho | — | `last_error` |
| `NAV2_ABORTED` | falha durante a execução | — | `last_error` |

- **Tradução no adaptador `fleet_ui`** (único lugar com conhecimento do formato bruto): resposta HTTP 200 cujo `message` contém `success=False` e `error_code='X'` (texto do `ros2 service call`) → `success: false`, `error_code: X`; 403 do backend com "não declarado em roles.yaml" → `UNKNOWN_ROBOT`; 403 com "não permite movimento" → `ROLE_NOT_ALLOWED`; 422 do FastAPI → `INVALID_REQUEST`; texto sem `success=False` → `success: true`, `error_code` vazio.
- **Log estruturado do SimFleet:** cada navegação falhada registra robô, destino, `error_code` e a causa detalhada (`target_occupied`, `target_out_of_map`, `no_path`). A causa não faz parte do contrato.
- **Apelidos e lugares nomeados não fazem parte do contrato de frota**, porque o Fleet UI não os tem. Eles vêm da configuração do cenário que o Fleet AI lê (o mesmo arquivo usado pelo SimFleet, ou um equivalente ao usar o Fleet UI).

### SimFleet

- **Cenário:** imagem do mapa de ocupação, resolução (m/pixel), origem, raio de inflação, resolução de planejamento, velocidade, robôs (id, papel, apelidos, pose inicial) e lugares nomeados (nome, sinônimos PT/EN, x, y, yaw). O papel é validado ao carregar: só `MUUT`, `FUUT` ou `SU`. O cenário padrão é o warehouse do `fleet-ui` (imagem `warehouse_map.png` e parâmetros do cenário de alocação de `windows-version`), com dois robôs MUUT, um FUUT e ao menos 5 lugares nomeados.
- **Grade de planejamento:** resolução `planning_resolution` (no cenário), obrigatoriamente múltiplo inteiro da resolução do mapa; valor não múltiplo impede o cenário de carregar. Sem o campo, usa-se o múltiplo mais próximo de 0,1 m. No warehouse, 0,09 m (3 × 0,03 m). Redução conservadora: a célula é bloqueada se qualquer pixel dela estiver bloqueado na grade inflada da resolução original. A célula de partida do robô é sempre considerada livre. O destino é válido se estiver livre na grade inflada original **e** na grade de planejamento. Lugares nomeados são validados nas duas grades ao carregar o cenário.
- **Caminho:** A* 8-conectado na grade de planejamento, sem cortar quinas, seguido de suavização por linha de visada; todo segmento do caminho final é validado contra a grade inflada da resolução original. O último ponto é exatamente o destino.
- **Movimento (MVP, não é simulação física fiel):** velocidade linear constante (`speed_mps`, padrão 0,3 m/s, no cenário); yaw alinhado a cada segmento instantaneamente; na chegada, assume o yaw pedido e volta a `idle`.
- **Relógio:** injetável. Em produção, relógio real com fator de escala configurável. Nos testes, relógio manual que avança um passo fixo a cada leitura de status, sem esperas reais.
- **Determinismo:** sem aleatoriedade; mesmo cenário e mesmos comandos produzem as mesmas poses.
- **Estado em memória:** reiniciar volta ao cenário inicial.

### API pública do Fleet AI

- `POST /v1/missions` com `{"instruction": str, "robot_id": str | null}` → `202 {"mission_id": str, "status": "running"}`. A missão roda em segundo plano.
- `GET /v1/missions/{mission_id}` → `{"mission_id", "status", "instruction", "robot_id", "planner", "language", "steps": [{"tool", "input", "result", "is_error"}], "final_text", "created_at", "finished_at"}`
- Status: `running`, `completed`, `not_understood`, `incomplete` (tempo máximo da missão, navegação que não terminou no prazo do Executor (`ExecutorTimeout`) ou, no planejador LLM, limite de turnos), `failed` (erro interno, cancelamento da tarefa ou backend de frota indisponível). `running` é o único status não terminal. `rejected` fica reservado e não é usado na SPEC-001: as guardas recusam com 422 ou 429 sem criar missão (ticket 09).
- Recusas: `422` entrada inválida (`invalid_request`: corpo malformado, instrução vazia ou longa demais, `robot_id` fora do formato `[A-Za-z0-9_-]{1,32}`), `429` taxa (`rate_limited`) ou concorrência (`too_many_missions`), com `Retry-After` em segundos. Corpo `{"error": <código>, "message": <texto>}`. `503` capacidade de retenção esgotada (`capacity_exhausted`), com `Retry-After` em segundos; esse valor é uma estimativa, não garantia de que haverá capacidade nesse momento. Uma recusa não cria missão, não devolve `mission_id`, não chega a planejar e não gasta cota de taxa.
- `GET /health` → `{"status", "fleet_adapter", "fleet_backend_reachable", "planner", "llm_enabled"}`
- Missões ficam em memória no MVP, com no máximo N missões retidas; só missões terminais são descartadas (ver Guardas).

### Encerramento garantido da missão (ticket 13)

- **Garantia:** enquanto o processo do Fleet AI estiver ativo, toda falha tratada leva a missão a um status terminal (`completed`, `not_understood`, `incomplete`, `failed`), com `finished_at` preenchido e os passos já executados preservados.
- **Mapeamento:** `ExecutorTimeout` → `incomplete`; `FleetBackendError` (inclusive falhas de transporte e respostas fora do contrato, ADR-0005) → `failed`; qualquer outra exceção da execução → `failed`; cancelamento da tarefa (`asyncio.CancelledError`) → `failed`, e o cancelamento é **repropagado**, não suprimido.
- **`ExecutorTimeout` sem cancelamento automático** nesta etapa: o texto final diz explicitamente que a navegação não terminou no prazo e que **o robô pode continuar navegando**; não afirma chegada nem cancelamento. Cancelar ao estourar o tempo máximo da missão é do ticket 08.
- **Passo que falhou:** quando uma ferramenta falha com `FleetBackendError` ou `ExecutorTimeout`, o passo é registrado com `is_error: true` e `result: {"error": "backend_unavailable" | "navigation_timeout", "message": <texto genérico>}` antes de a falha subir.
- **Sem vazamento:** a resposta da missão nunca contém mensagens do backend, texto de exceção, rastros de pilha, URLs internas ou credenciais; o texto final é genérico ("o backend de frota está indisponível", "erro interno"). Os detalhes vão para um log estruturado com `mission_id`, tipo da falha e a mensagem diagnóstica.
- **Limites da garantia:** não há recuperação depois de um reinício (as missões vivem em memória e se perdem), nem proteção contra uma operação que bloqueie indefinidamente sem lançar exceção. A espera de cada chamada HTTP é limitada pelo timeout do cliente do adaptador e a espera da navegação pelo timeout do Executor; o tempo máximo da missão como um todo é do ticket 08.

### Guardas (valores padrão, todos configuráveis)

| Limite | Padrão |
|---|---|
| Tamanho da instrução | 300 caracteres |
| Missões por IP | 10 por minuto, 100 por dia |
| Missões simultâneas, global | 4 |
| Tempo máximo de uma missão | 60 s |
| Prazo para confirmar o cancelamento depois do tempo máximo | 5 s |
| Missões retidas em memória | 500 |
| Turnos do planejador LLM por missão | 8 |

- O IP do cliente vem da conexão; `X-Forwarded-For` só é usado se a conexão vier de um proxy confiável configurado, e então vale o endereço mais à direita que não é de um proxy confiável.
- Rate limit e concorrência em memória (um processo). A taxa usa janelas deslizantes de 60 s e de 24 h e só conta missões aceitas; uma recusa por concorrência não gasta cota.
- **Limpeza do limitador** (ticket 14): o limitador só guarda IPs com missão aceita nas últimas 24 h; consultar um IP não cria registro. Registros com mais de 24 h são removidos de forma oportunista nas próprias chamadas do limitador (no máximo uma varredura completa por minuto do relógio), sem tarefa periódica. A limpeza não altera os limites por minuto e por dia de quem ainda tem missões nas janelas. Isso remove registros obsoletos, **mas não estabelece um teto absoluto de memória**: muitos IPs distintos com missões nas últimas 24 h continuam guardados. O limite de taxa bruto no proxy reverso é pré-requisito do deploy público.
- **Retenção segura** (ticket 14): acima do teto de missões retidas, sai a missão **terminal** mais antiga; missões `running` nunca são descartadas. Quando a retenção estiver cheia e não existir missão terminal elegível para descarte, a criação é recusada com `503 capacity_exhausted`.
- **Admissão atômica** (ticket 14): as decisões de admissão (validação, taxa, concorrência, capacidade, registro na cota e inserção da missão) acontecem sem pausa assíncrona entre a checagem e a inserção. A garantia vale para um processo com um event loop; com mais de um processo ou réplica, cada um decide sozinho.
- Variáveis de ambiente: `FLEET_AI_MAX_INSTRUCTION_CHARS`, `FLEET_AI_MISSIONS_PER_MINUTE`, `FLEET_AI_MISSIONS_PER_DAY`, `FLEET_AI_MAX_CONCURRENT`, `FLEET_AI_MISSIONS_RETAINED`, `FLEET_AI_MISSION_TIMEOUT`, `FLEET_AI_CANCEL_GRACE` e `FLEET_AI_TRUSTED_PROXIES` (lista separada por vírgula). Valor inválido impede o serviço de subir.

### Configuração

Por ambiente: adaptador de frota (`sim` ou `fleet_ui`) e URL do backend; caminho do cenário; planejador (`deterministic`, padrão, ou `llm`); adaptador de LLM (só `scripted` na SPEC-001) e caminho do roteiro; limites acima; proxies confiáveis. Nenhuma variável de chave de API existe na SPEC-001.

### Docker

Duas imagens, usuário não-root, healthcheck, limite de memória. No Compose local, só o Fleet AI publica porta (em `127.0.0.1`); o SimFleet fica na rede interna.

## Testing Decisions

- **O que é um bom teste aqui:** exercita comportamento externo pela seam combinada e verifica resultados observáveis (status, passos, pose final, texto final, códigos HTTP). Não verifica chamadas internas nem estrutura de classes.
- **Seam principal:** a API HTTP do Fleet AI, em processo, ligada a um SimFleet real em processo com relógio manual. Missões com o planejador determinístico e com o planejador LLM + LLM roteirizado passam pela mesma seam.
- **Tabela de intenções:** casos instrução → (intenção, argumentos, idioma) ou `not_understood`, em português e inglês, verificados pela API de missões (plano observado nos passos). A tabela é o documento vivo do que o planejador entende.
- **Seam de contrato:** uma suíte única, parametrizada por adaptador, roda pelo Executor contra o SimFleet (adaptador `sim`) e contra o fake do Fleet UI (adaptador `fleet_ui`). O fake emite as respostas **brutas** do `fleet-ui@a57a3b1` (HTTP 200 com texto do `ros2 service call`, 403 do backend, 422 do FastAPI, navegação assíncrona e o `NAV2_ABORTED` após cancelamento); a suíte espera o contrato normalizado nos dois.
- **Seam do SimFleet:** a própria API HTTP do SimFleet, para navegação, recusas, códigos de erro, log estruturado e determinismo.
- **Encerramento garantido:** cenários de falha (backend fora do ar, respostas inválidas, prazo do Executor, exceção inesperada, cancelamento da tarefa) verificados pela API de missões e um invariante parametrizado: toda missão sai de `running` com `finished_at`. O cancelamento da tarefa é testado executando a missão numa tarefa `asyncio` e cancelando-a (ticket 13).
- **Garantia de custo zero:** um teste verifica que a suíte inteira e o serviço sobem sem nenhuma variável de chave de API e que nenhuma dependência de SDK de LLM pago está declarada.
- **Fora da suíte:** checklist manual contra o Fleet UI real.
- **Referências no `fleet-ui`:** testes do Planner com cliente falso, do Executor via transporte ASGI em memória, e dos endpoints de agente e de frota.
- **Verificações contínuas:** testes, lint e checagem de tipos a cada ticket.

## Out of Scope

- **Integração com modelos reais** (Anthropic ou outros), chaves de API, orçamento de tokens e custo e livro de uso. Ficam para uma spec futura, opcional e desligada por padrão (ver ADR-0004).
- Planejamento por modelos locais.
- Mais de uma intenção por instrução ("vá até A e depois até B"), negação e condicionais.
- Alocação de missões entre robôs e decomposição de missões.
- Servidor MCP; coordenação entre agentes; execução de N agentes em paralelo.
- Gravação, replay, coleta de sensores, experimentos, campanhas e o Analyst.
- Streaming de passos; interface web; integração com o portfólio.
- Deploy na VPS, TLS, proxy reverso, Redis, captcha.
- Física realista (aceleração, tempo de giro, dinâmica), colisão entre robôs, obstáculos dinâmicos e ruído no SimFleet.
- Qualquer alteração no repositório `fleet-ui`.

## Further Notes

- Antes do deploy público na VPS: limite de taxa bruto no proxy reverso (inclusive para requisições inválidas, que não gastam cota) e, se necessário, um teto absoluto de IPs rastreados; o ticket 14 só remove registros expirados.

- O timeout do Executor (padrão 120 s) é maior que o tempo máximo da missão (60 s, tabela de guardas). Resolvido no ticket 08: a missão inteira roda sob o tempo máximo, então nenhuma espera do Executor passa dele; ao estourar, a navegação em curso enviada pela missão é cancelada com verificação (prazo de 5 s para confirmar) e a missão termina `incomplete`, com o texto relatando só o resultado do cancelamento. Se o prazo do Executor for menor que o tempo restante, vale o `ExecutorTimeout` (ticket 13, sem cancelamento).

- A demo pública deve dizer que o planejamento é determinístico (por regras) e que a simulação é 2D cinemática, não Gazebo. Não chamar o planejador determinístico de "IA" na interface.
- O planejador LLM existe na SPEC-001 só para manter o loop do `fleet-ui` portado, testado e pronto; ligá-lo com um modelo real exige a spec futura.
- Antes de integrar robôs reais (adaptador `fleet_ui` em uso), revisar a política de `ExecutorTimeout` e de cancelamento verificado: ver ADR-0006 (proposto). A SPEC-001 mantém `ExecutorTimeout` → `incomplete` sem cancelamento.
- A brecha de escopo por `run_id` do `fleet-ui` não se aplica: nenhuma ferramenta do MVP recebe `run_id`.
- O Fleet UI de referência expõe `/api/*` sem autenticação; usar o adaptador `fleet_ui` fora de uma rede confiável não é suportado.
