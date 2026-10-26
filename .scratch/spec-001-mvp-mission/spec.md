# SPEC-001: MVP — missão em linguagem natural contra o SimFleet

**Status:** ready-for-agent
**Aprovada em:** 2026-10-26
**Referência de código:** `fleet-ui@a57a3b1` (ver ADR-0001)
**Decisões relacionadas:** ADR-0001, ADR-0002, ADR-0003

## Problem Statement

Os agentes do Fleet UI só funcionam com ROS 2, Nav2 e Gazebo rodando numa
máquina de desenvolvimento potente. Por isso não dá para demonstrá-los
publicamente, testá-los de ponta a ponta sem a simulação completa, nem
evoluí-los com segurança. Além disso, a API de agentes não tem proteção contra
abuso nem contra gasto descontrolado com o LLM: qualquer pessoa com acesso ao
backend consome a chave da Anthropic do dono.

## Solution

O Fleet AI é um serviço independente que recebe uma **missão** em linguagem
natural e a executa com um agente que só enxerga **ferramentas** de alto nível.
As ferramentas chamam um **backend de frota** pelo **contrato de frota** HTTP.
Há dois backends intercambiáveis: o **SimFleet** (2D, sem ROS, roda em qualquer
máquina) e o **Fleet UI** original. O dono acompanha o resultado de cada missão,
com os passos, o uso de tokens e o custo estimado, e o serviço recusa pedidos
que excedam limites de tamanho, taxa, tokens ou orçamento.

O MVP cobre navegação: listar robôs, consultar estado, mover, aguardar chegada e
cancelar. Gravação, replay, campanhas e o Analyst ficam para specs seguintes.

## User Stories

1. Como visitante da demo, quero enviar uma missão como "leve o tb1 até a doca de carga" e receber um identificador de missão, para acompanhar a execução.
2. Como visitante, quero consultar a missão e ver o status (`running`, `completed`, `incomplete`, `failed`, `rejected`), para saber se ela terminou.
3. Como visitante, quero ver cada passo que o agente executou, com a entrada e o resultado, para entender como ele chegou ao resultado.
4. Como visitante, quero um texto final do agente resumindo o que foi feito, para não precisar interpretar os passos.
5. Como visitante, quero que pedir um robô inexistente gere uma explicação clara, e não um erro genérico.
6. Como visitante, quero que pedir um destino dentro de uma parede ou fora do mapa gere uma explicação clara do agente.
7. Como visitante, quero que pedir movimento a um robô de papel FUUT ou SU seja recusado com o motivo, como no Fleet UI.
8. Como visitante, quero ver a pose final do robô no resultado, para confirmar que ele chegou.
9. Como dono, quero que instruções acima do tamanho máximo sejam rejeitadas antes de qualquer chamada ao LLM, para não gastar tokens.
10. Como dono, quero limitar quantas missões um mesmo IP pode criar por minuto e por dia, para conter bots.
11. Como dono, quero limitar quantas missões rodam ao mesmo tempo, para proteger CPU, memória e a API.
12. Como dono, quero um teto de tokens e de custo por missão, para que uma missão que entre em loop pare sozinha.
13. Como dono, quero um teto de custo diário global que sobreviva a reinícios do serviço, para ter previsibilidade de gasto.
14. Como dono, quero ver tokens de entrada, de saída e custo estimado de cada missão, para acompanhar o orçamento.
15. Como dono, quero configurar modelo, preços por token e limites por variável de ambiente, para mudar sem alterar código.
16. Como dono, quero que a chave da Anthropic venha só do ambiente e nunca apareça em logs nem em respostas.
17. Como dono, quero que o serviço recuse subir com o adaptador real de LLM se não houver chave configurada, para falhar cedo.
18. Como pesquisador, quero apontar o Fleet AI para o Fleet UI real só trocando a configuração do adaptador, para que demo e laboratório usem o mesmo agente.
19. Como pesquisador, quero restringir uma missão a um único robô, de forma estrutural, para que o agente nunca comande outro robô mesmo se o modelo pedir.
20. Como pesquisador, quero que o SimFleet carregue um cenário (mapa, resolução, origem, robôs com papel e pose inicial), para reproduzir o ambiente do warehouse.
21. Como pesquisador, quero que a mesma missão no mesmo cenário produza o mesmo resultado no SimFleet, para depurar e comparar.
22. Como desenvolvedor, quero testar a missão de ponta a ponta sem rede e sem custo, com o LLM roteirizado, para rodar a suíte a cada mudança.
23. Como desenvolvedor, quero uma suíte de testes de contrato que rode contra o SimFleet e contra o fake do Fleet UI, para garantir que os backends são intercambiáveis.
24. Como desenvolvedor, quero que, ao atingir o limite de turnos, a missão termine como `incomplete` com os passos preservados, em vez de perder o trabalho.
25. Como desenvolvedor, quero que um erro de ferramenta volte ao modelo como resultado de erro, para que ele possa se corrigir.
26. Como operador, quero endpoints de health nos dois serviços, informando o adaptador ativo e se o backend de frota responde.
27. Como operador, quero subir Fleet AI e SimFleet localmente com Docker Compose, com o SimFleet sem porta publicada, para reproduzir o ambiente da VPS.
28. Como operador, quero logs estruturados com `mission_id`, sem conteúdo sensível, para investigar problemas.

## Implementation Decisions

### Módulos

- **Serviço Fleet AI (FastAPI):** API pública de missões, Planner, porta de LLM, Executor, guardas (validação, taxa, concorrência, orçamento), livro de uso e configuração.
- **Serviço SimFleet (FastAPI):** implementa o contrato de frota sobre um cenário. Processo e imagem próprios.
- **Planner:** portado do `fleet-ui`. Mudanças: recebe a porta de LLM, o modelo e os limites por injeção; devolve status em vez de lançar exceção ao atingir o limite de turnos; contabiliza uso por chamada.
- **Executor:** portado do `fleet-ui`, incluindo a correção de pose por robô. Ganha a operação composta de aguardar chegada, feita por polling do status com intervalo e timeout configuráveis.
- **Porta de LLM:** recebe sistema, mensagens, ferramentas e limite de tokens; devolve blocos de conteúdo, motivo de parada e uso (tokens de entrada e de saída). Implementações: Anthropic (real) e LLM roteirizado.

### Ferramentas do MVP

| Ferramenta | Contrato de frota |
|---|---|
| `list_robots` | `GET /api/list_robots` |
| `get_robot_status` | `GET /api/status` (filtra o robô; pose de `poses[robot_id]`) |
| `move_robot` | `POST /api/go_to_point` |
| `wait_for_arrival` | polling de `GET /api/status` até `nav_state` sair de `navigating` |
| `cancel_navigation` | `POST /api/cancel` |

As demais ferramentas do `fleet-ui` (gravação, replay, coleta, experimentos, campanhas, Analyst) não são expostas na SPEC-001.

### Contrato de frota (subconjunto, igual ao `fleet-ui@a57a3b1`)

- `GET /api/list_robots` → `{"robot_ids": [...]}`
- `GET /api/status` → `{"robots": [{"robot_id", "role", "nav_state", "current_route", "collection_on", "collection_file", "last_error", "bytes_written"}], "pose": {...}, "poses": {robot_id: {"x", "y", "yaw", "valid"}}}`
- `POST /api/go_to_point?robot_id&x&y&yaw` → `{"success": bool, "message": str}`. Papel diferente de MUUT → HTTP 403 com `{"success": false, "message": "<robot_id>: papel '<role>' não permite movimento"}`.
- `POST /api/cancel?robot_id` → `{"success": bool, "message": str}`
- `nav_state` usa os valores do Fleet UI: `idle`, `navigating`, `failed` (`recording` existe no Fleet UI, mas o SimFleet não o produz no MVP).
- O SimFleet responde destino inalcançável (célula ocupada, fora do mapa ou sem caminho) com `{"success": false, "message": ...}` e HTTP 200, e o robô fica em `failed` com `last_error` preenchido.

### SimFleet

- **Cenário:** imagem do mapa de ocupação, resolução (m/pixel), origem, raio de inflação e robôs (id, papel, pose inicial). O cenário padrão é o warehouse do `fleet-ui` (imagem `warehouse_map.png` e parâmetros do cenário de alocação de `windows-version`), com 3 robôs: dois MUUT e um FUUT.
- **Navegação:** A* 8-conectado sobre a grade com obstáculos inflados; o robô percorre o caminho a velocidade linear constante, com yaw na direção do movimento; na chegada, assume o yaw pedido e volta a `idle`.
- **Relógio:** a simulação avança por um relógio injetável. Em produção, relógio real multiplicado por um fator de escala configurável. Nos testes, relógio manual que avança um passo fixo a cada leitura de status, sem esperas reais.
- **Determinismo:** sem aleatoriedade no MVP; mesmo cenário e mesmos comandos produzem as mesmas poses.
- **Estado em memória:** reiniciar o SimFleet volta ao cenário inicial.

### API pública do Fleet AI

- `POST /v1/missions` com `{"instruction": str, "robot_id": str | null}` → `202 {"mission_id": str, "status": "running"}`. A missão roda em segundo plano.
- `GET /v1/missions/{mission_id}` → `{"mission_id", "status", "instruction", "robot_id", "steps": [{"tool", "input", "result", "is_error"}], "final_text", "usage": {"input_tokens", "output_tokens", "estimated_cost_usd"}, "created_at", "finished_at"}`
- Status: `running`, `completed` (o modelo terminou sem pedir ferramenta), `incomplete` (limite de turnos, tokens ou custo da missão), `failed` (erro interno ou do backend de frota fora das ferramentas), `rejected` (barrada por uma guarda antes de começar).
- Respostas de recusa: `422` para entrada inválida, `429` para taxa ou concorrência (com `Retry-After`), `503` para orçamento diário esgotado. Corpo `{"error": <código>, "message": <texto>}`.
- `GET /health` → `{"status", "fleet_adapter", "fleet_backend_reachable", "llm_adapter"}`
- Missões ficam em memória no MVP; o **livro de uso** (missão, tokens, custo, data) é persistido em SQLite.

### Guardas e orçamento (valores padrão, todos configuráveis)

| Limite | Padrão |
|---|---|
| Tamanho da instrução | 500 caracteres |
| Turnos do Planner por missão | 8 |
| Tokens de saída por chamada ao LLM | 1.024 |
| Tokens totais por missão (entrada + saída) | 30.000 |
| Custo estimado por missão | US$ 0,10 |
| Custo estimado por dia (UTC), global, persistido | US$ 1,00 |
| Missões por IP | 5 por minuto, 20 por dia |
| Missões simultâneas, global | 2 |
| Tempo máximo de uma missão | 120 s |

- O custo é estimado a partir do uso devolvido pelo LLM e de uma tabela de preços por modelo vinda da configuração; nenhum preço fica fixo no código.
- Antes de cada chamada ao LLM, o Planner confere se a próxima chamada pode estourar o teto de tokens ou de custo da missão; se puder, encerra como `incomplete`.
- O orçamento diário é conferido ao criar a missão e antes de cada chamada ao LLM.
- O IP do cliente vem da conexão; `X-Forwarded-For` só é usado se a conexão vier de um proxy confiável configurado.
- Rate limit e concorrência ficam em memória (um processo); Redis fica para uma spec de deploy.

### Configuração

Por ambiente: adaptador de frota (`sim` ou `fleet_ui`) e URL do backend; adaptador de LLM (`anthropic` ou `scripted`, este só para testes e desenvolvimento); modelo (recomendado `claude-sonnet-5-5`, a confirmar na implementação contra os modelos disponíveis); chave da Anthropic; tabela de preços; limites acima; caminho do livro de uso; proxies confiáveis.

### Sistema de prompt

Mantém as regras do `fleet-ui`: nunca inventar robôs ou valores não devolvidos por uma ferramenta, conferir o estado antes de mover e resumir o resultado no fim. Acrescenta: aguardar a chegada antes de declarar sucesso, e responder sempre no idioma da instrução.

### Docker

Duas imagens, usuário não-root, healthcheck, limite de memória. No Compose local, só o Fleet AI publica porta (em `127.0.0.1`); o SimFleet fica na rede interna.

## Testing Decisions

- **O que é um bom teste aqui:** exercita comportamento externo pela seam combinada e verifica resultados observáveis (status, passos, pose final, códigos HTTP, livro de uso). Não verifica chamadas internas, ordem de métodos privados ou estrutura de classes.
- **Seam principal:** a API HTTP do Fleet AI, em processo, ligada a um SimFleet real em processo (com relógio manual) e ao LLM roteirizado. A maioria dos testes de comportamento vive aqui.
- **Seam de contrato:** uma suíte única, parametrizada por backend, roda pelo Executor contra o SimFleet e contra o fake do Fleet UI. O fake reproduz caminhos, parâmetros, formatos e erros do `fleet-ui@a57a3b1`.
- **Seam do SimFleet:** a própria API HTTP do SimFleet, para navegação, recusas e determinismo.
- **Fora da suíte padrão:** teste de fumaça com a API real da Anthropic (opt-in, marcado) e checklist manual contra o Fleet UI real.
- **Referências no `fleet-ui`:** testes do Planner com cliente falso, do Executor via transporte ASGI em memória, e dos endpoints de agente e de frota. Eles mostram o padrão; não são copiados sem adaptação.
- **Verificações contínuas:** testes, lint e checagem de tipos rodam localmente a cada ticket.

## Out of Scope

- Alocação de missões entre robôs (fixa, gulosa, ótima ou por LLM) e decomposição de missões.
- Servidor MCP.
- Coordenação ou negociação entre agentes; execução de N agentes em paralelo (`run_fleet`).
- Gravação, replay, coleta de sensores, experimentos, campanhas e o Analyst.
- Streaming (SSE ou WebSocket) de passos; a consulta é por polling.
- Interface web e integração com o portfólio.
- Deploy na VPS, TLS, proxy reverso, Redis, Turnstile/captcha.
- Avaliação da qualidade das decisões do modelo.
- Física realista, colisão entre robôs e ruído no SimFleet.
- Qualquer alteração no repositório `fleet-ui`.

## Further Notes

- A interface pública futura deve dizer que a demo roda numa simulação 2D cinemática, não no Gazebo.
- A brecha de escopo por `run_id` do `fleet-ui` não se aplica aqui, porque nenhuma ferramenta do MVP recebe `run_id`. Ela volta a valer quando o Analyst for portado.
- O Fleet UI de referência expõe `/api/*` sem autenticação. Usar o adaptador `fleet_ui` fora de uma rede confiável não é suportado.
- Os bags MCAP reais existem só no disco da máquina de desenvolvimento; fazer backup é pré-requisito de specs futuras de robótica, não desta.
