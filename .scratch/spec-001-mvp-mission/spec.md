# SPEC-001: MVP — missão em linguagem natural contra o SimFleet, sem LLM pago

**Status:** ready-for-agent
**Aprovada em:** 2026-10-26 (revisada no mesmo dia: sem APIs pagas, ver ADR-0004)
**Referência de código:** `fleet-ui@a57a3b1` (ver ADR-0001)
**Decisões relacionadas:** ADR-0001, ADR-0002, ADR-0003, ADR-0004

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
11. Como visitante, quero que pedir movimento a um robô de papel FUUT ou SU seja recusado com o motivo, como no Fleet UI.
12. Como visitante, quero referir-me aos robôs pelo id ("tb1") ou por apelidos do cenário ("robô 1", "robot one"), e aos lugares por nome ou sinônimo, sem me preocupar com maiúsculas ou acentos.
13. Como dono, quero que a demo funcione sem nenhuma chave de API e sem nenhuma dependência de SDK de LLM pago, para ter custo zero de modelo.
14. Como dono, quero que o planejador LLM fique desligado por padrão e só possa ser ligado por configuração explícita, para que ninguém o ative por engano.
15. Como dono, quero que instruções acima do tamanho máximo sejam rejeitadas antes de qualquer planejamento.
16. Como dono, quero limitar quantas missões um mesmo IP pode criar por minuto e por dia, para conter bots que esgotariam CPU e memória.
17. Como dono, quero limitar quantas missões rodam ao mesmo tempo e quanto tempo cada uma pode durar.
18. Como pesquisador, quero apontar o Fleet AI para o Fleet UI real só trocando a configuração do adaptador de frota.
19. Como pesquisador, quero restringir uma missão a um único robô, de forma estrutural, para que nenhuma instrução comande outro robô.
20. Como pesquisador, quero que o SimFleet carregue um cenário (mapa, resolução, origem, robôs com papel, apelidos e pose inicial, e lugares nomeados), para reproduzir o ambiente do warehouse.
21. Como pesquisador, quero que a mesma instrução no mesmo cenário produza sempre o mesmo plano e as mesmas poses, para depurar e comparar.
22. Como desenvolvedor, quero testar as intenções do planejador determinístico com uma tabela de casos (instrução → plano esperado) em português e inglês.
23. Como desenvolvedor, quero testar o loop do planejador LLM de ponta a ponta com o LLM roteirizado, sem rede e sem custo, para que a integração futura com um modelo real seja só um novo adaptador.
24. Como desenvolvedor, quero que os dois planejadores usem as mesmas ferramentas, o mesmo escopo de robô e o mesmo registro de passos, para que a missão tenha o mesmo formato independentemente do planejador.
25. Como desenvolvedor, quero uma suíte de testes de contrato que rode contra o SimFleet e contra o fake do Fleet UI.
26. Como desenvolvedor, quero que, no planejador LLM, o limite de turnos termine a missão como `incomplete` com os passos preservados.
27. Como operador, quero endpoints de health nos dois serviços, informando o adaptador de frota, se o backend responde e o planejador ativo.
28. Como operador, quero subir Fleet AI e SimFleet localmente com Docker Compose, com o SimFleet sem porta publicada.
29. Como operador, quero logs estruturados com `mission_id`.

## Implementation Decisions

### Módulos

- **Serviço Fleet AI (FastAPI):** API pública de missões, executor de missões, planejadores, ferramentas, Executor, guardas e configuração.
- **Serviço SimFleet (FastAPI):** implementa o contrato de frota sobre um cenário. Processo e imagem próprios.
- **Executor:** portado do `fleet-ui`, com a correção de pose por robô, mais a operação composta de aguardar chegada (polling do status com intervalo e timeout configuráveis).
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
- **Não entendido:** sem intenção reconhecida, robô ausente quando a intenção exige um, ou mais de uma intenção na mesma instrução → status `not_understood`, sem chamar nenhuma ferramenta, com 3 exemplos de instruções válidas no idioma detectado.
- **Lugar ou robô desconhecido:** `not_understood` com a lista de nomes válidos do cenário.
- **Falha de ferramenta** (papel sem movimento, destino inválido): o plano para no passo que falhou e a missão termina `completed` com o texto final explicando a falha (a missão foi entendida e executada até onde o backend permitiu).
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
| `wait_for_arrival` | polling de `GET /api/status` até `nav_state` sair de `navigating` |
| `cancel_navigation` | `POST /api/cancel` |

As demais ferramentas do `fleet-ui` (gravação, replay, coleta, experimentos, campanhas, Analyst) não entram na SPEC-001.

### Contrato de frota (subconjunto, igual ao `fleet-ui@a57a3b1`)

- `GET /api/list_robots` → `{"robot_ids": [...]}`
- `GET /api/status` → `{"robots": [{"robot_id", "role", "nav_state", "current_route", "collection_on", "collection_file", "last_error", "bytes_written"}], "pose": {...}, "poses": {robot_id: {"x", "y", "yaw", "valid"}}}`
- `POST /api/go_to_point?robot_id&x&y&yaw` → `{"success": bool, "message": str}`. Papel diferente de MUUT → HTTP 403 com `{"success": false, "message": "<robot_id>: papel '<role>' não permite movimento"}`.
- `POST /api/cancel?robot_id` → `{"success": bool, "message": str}`
- `nav_state` usa os valores do Fleet UI: `idle`, `navigating`, `failed`.
- Destino inalcançável no SimFleet (ocupado, fora do mapa, sem caminho) → HTTP 200 com `{"success": false, "message": ...}`; robô em `failed` com `last_error`.
- **Apelidos e lugares nomeados não fazem parte do contrato de frota**, porque o Fleet UI não os tem. Eles vêm da configuração do cenário que o Fleet AI lê (o mesmo arquivo usado pelo SimFleet, ou um equivalente ao usar o Fleet UI).

### SimFleet

- **Cenário:** imagem do mapa de ocupação, resolução (m/pixel), origem, raio de inflação, robôs (id, papel, apelidos, pose inicial) e lugares nomeados (nome, sinônimos PT/EN, x, y, yaw). O cenário padrão é o warehouse do `fleet-ui` (imagem `warehouse_map.png` e parâmetros do cenário de alocação de `windows-version`), com dois robôs MUUT, um FUUT e ao menos 5 lugares nomeados.
- **Navegação:** A* 8-conectado sobre a grade com obstáculos inflados; velocidade linear constante, yaw na direção do movimento; na chegada, assume o yaw pedido e volta a `idle`.
- **Relógio:** injetável. Em produção, relógio real com fator de escala configurável. Nos testes, relógio manual que avança um passo fixo a cada leitura de status, sem esperas reais.
- **Determinismo:** sem aleatoriedade; mesmo cenário e mesmos comandos produzem as mesmas poses.
- **Estado em memória:** reiniciar volta ao cenário inicial.

### API pública do Fleet AI

- `POST /v1/missions` com `{"instruction": str, "robot_id": str | null}` → `202 {"mission_id": str, "status": "running"}`. A missão roda em segundo plano.
- `GET /v1/missions/{mission_id}` → `{"mission_id", "status", "instruction", "robot_id", "planner", "language", "steps": [{"tool", "input", "result", "is_error"}], "final_text", "created_at", "finished_at"}`
- Status: `running`, `completed`, `not_understood`, `incomplete` (tempo máximo ou, no planejador LLM, limite de turnos), `failed` (erro interno ou backend de frota indisponível), `rejected` (barrada por uma guarda).
- Recusas: `422` entrada inválida, `429` taxa ou concorrência (com `Retry-After`). Corpo `{"error": <código>, "message": <texto>}`.
- `GET /health` → `{"status", "fleet_adapter", "fleet_backend_reachable", "planner", "llm_enabled"}`
- Missões ficam em memória no MVP, com no máximo N missões retidas (as mais antigas são descartadas).

### Guardas (valores padrão, todos configuráveis)

| Limite | Padrão |
|---|---|
| Tamanho da instrução | 300 caracteres |
| Missões por IP | 10 por minuto, 100 por dia |
| Missões simultâneas, global | 4 |
| Tempo máximo de uma missão | 60 s |
| Missões retidas em memória | 500 |
| Turnos do planejador LLM por missão | 8 |

- O IP do cliente vem da conexão; `X-Forwarded-For` só é usado se a conexão vier de um proxy confiável configurado.
- Rate limit e concorrência em memória (um processo).

### Configuração

Por ambiente: adaptador de frota (`sim` ou `fleet_ui`) e URL do backend; caminho do cenário; planejador (`deterministic`, padrão, ou `llm`); adaptador de LLM (só `scripted` na SPEC-001) e caminho do roteiro; limites acima; proxies confiáveis. Nenhuma variável de chave de API existe na SPEC-001.

### Docker

Duas imagens, usuário não-root, healthcheck, limite de memória. No Compose local, só o Fleet AI publica porta (em `127.0.0.1`); o SimFleet fica na rede interna.

## Testing Decisions

- **O que é um bom teste aqui:** exercita comportamento externo pela seam combinada e verifica resultados observáveis (status, passos, pose final, texto final, códigos HTTP). Não verifica chamadas internas nem estrutura de classes.
- **Seam principal:** a API HTTP do Fleet AI, em processo, ligada a um SimFleet real em processo com relógio manual. Missões com o planejador determinístico e com o planejador LLM + LLM roteirizado passam pela mesma seam.
- **Tabela de intenções:** casos instrução → (intenção, argumentos, idioma) ou `not_understood`, em português e inglês, verificados pela API de missões (plano observado nos passos). A tabela é o documento vivo do que o planejador entende.
- **Seam de contrato:** uma suíte única, parametrizada por backend, roda pelo Executor contra o SimFleet e contra o fake do Fleet UI, que reproduz caminhos, parâmetros, formatos e erros do `fleet-ui@a57a3b1`.
- **Seam do SimFleet:** a própria API HTTP do SimFleet, para navegação, recusas e determinismo.
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
- Física realista, colisão entre robôs e ruído no SimFleet.
- Qualquer alteração no repositório `fleet-ui`.

## Further Notes

- A demo pública deve dizer que o planejamento é determinístico (por regras) e que a simulação é 2D cinemática, não Gazebo. Não chamar o planejador determinístico de "IA" na interface.
- O planejador LLM existe na SPEC-001 só para manter o loop do `fleet-ui` portado, testado e pronto; ligá-lo com um modelo real exige a spec futura.
- A brecha de escopo por `run_id` do `fleet-ui` não se aplica: nenhuma ferramenta do MVP recebe `run_id`.
- O Fleet UI de referência expõe `/api/*` sem autenticação; usar o adaptador `fleet_ui` fora de uma rede confiável não é suportado.
