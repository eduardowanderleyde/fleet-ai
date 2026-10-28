# 01: Interface web local do Fleet AI (Control Center)

**What to build:** Uma página servida pelo próprio Fleet AI, em HTML, CSS e JavaScript simples (sem Next.js, sem bundler, sem CDN), que mostra o mapa 2D do cenário com obstáculos, lugares e robôs, atualiza posições e estados por polling a cada 1 s, envia comandos em português por `POST /v1/missions`, acompanha cada missão (status, passos, texto final) e mostra a saúde da API e do backend de frota. Tudo roda só em `127.0.0.1` e é acessado pelo túnel SSH. O navegador fala apenas com o Fleet AI; o SimFleet nunca fica exposto a ele.

Primeiro ticket da SPEC-003 (README, roadmap: "interface web"). Streaming de passos continua fora: esta versão usa polling. Nenhum LLM, SDK externo ou serviço adicional é necessário.

**Blocked by:** SPEC-001 tickets 10 e 11 (concluídos). Não depende do ticket 15 enquanto ficar em `127.0.0.1`; exposição pública depende do ticket 15 e de controle de acesso.

**Status:** resolved

## O que já existe (inspecionado em 2026-10-28)

| Fonte | Endpoint | Dados |
|---|---|---|
| SimFleet | `GET /api/status` | por robô: `robot_id`, `role`, `nav_state`, `last_error`; `poses` com `x`, `y`, `yaw`, `valid` |
| SimFleet | `GET /api/list_robots` | ids |
| SimFleet | (nenhum) | o mapa (`warehouse_map.png`, 1006 x 1674 px, 0,03 m/px, origem (-15,1; -25,0)) só existe dentro do processo |
| Fleet UI (`a57a3b1`) | `GET /api/map` | `{"available", "robot_id", "resolution", "origin_x", "origin_y", "width", "height", "png_b64"}`; `available: false` sem mapa |
| Fleet AI | `GET /health`, `GET /health/live` | readiness e liveness (ticket 11) |
| Fleet AI | `POST /v1/missions`, `GET /v1/missions/{id}` | criar e consultar uma missão |
| Fleet AI | (nenhum) | lista de missões, estado da frota, mapa, lugares |

Os lugares nomeados já são lidos pelo Fleet AI do mesmo `scenario.toml` (ADR-0005: apelidos e lugares não fazem parte do contrato de frota).

## Arquitetura proposta

```
navegador (túnel SSH) ──► Fleet AI 127.0.0.1:8000
                            ├─ GET /            → index.html + /static/app.js, app.css
                            ├─ GET /v1/fleet    → adaptador.status()  ─► backend de frota
                            ├─ GET /v1/map      → adaptador.map()     ─► backend de frota
                            ├─ GET /v1/map/image.png
                            ├─ GET/POST /v1/missions, GET /v1/missions/{id}
                            └─ GET /health, /health/live
```

- **Estático:** `src/fleet_ai/web/` com `index.html`, `app.js` (módulo ES, sem dependências) e `app.css`, servidos pelo FastAPI (`StaticFiles`). Desenho em `<canvas>`.
- **Mapa:** o SimFleet ganha `GET /api/map` no **mesmo formato do Fleet UI**, então um único método `map()` nos dois adaptadores atende a interface. O Fleet AI valida o PNG (assinatura, tamanho máximo de 8 MB, dimensões coerentes com `width` e `height`) e o serve em `/v1/map/image.png`; os metadados e os lugares saem em `/v1/map`. Sem mapa (`available: false`, ou o Fleet UI sem SLAM), a interface desenha uma grade simples em volta dos robôs e dos lugares.
- **Coordenadas:** pixel x = (x − origin_x) / resolution; pixel y = height − (y − origin_y) / resolution (o PNG tem a primeira linha no topo).
- **Polling:** `/v1/fleet` a cada 1 s; a missão acompanhada a cada 1 s enquanto `running`; `/health` a cada 5 s (o cache da readiness é de 5 s). Depois de uma falha, recuo de 1, 2, 4 até 10 s, com o aviso "sem conexão" e as últimas posições marcadas como desatualizadas.
- **Segurança da página:** só `textContent` e `createElement` para texto vindo da API; nenhum `innerHTML`, `insertAdjacentHTML`, `document.write` ou `eval`. Cabeçalhos `Content-Security-Policy: default-src 'self'; img-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'`, `X-Content-Type-Options: nosniff` e `Referrer-Policy: no-referrer`. Sem scripts inline e sem recursos externos.
- **Honestidade da demo** (SPEC-001, Further Notes): o painel diz "planejador determinístico (por regras)" e "simulação 2D cinemática"; nunca chama o determinístico de IA.
- **Execução:** `scripts/demo.sh` sobe os dois serviços em `127.0.0.1` com `SIMFLEET_TIME_SCALE=3` (a 0,3 m/s, a ida até a doca leva cerca de 60 s, o tempo máximo da missão, como se viu no primeiro teste na VPS) e imprime o comando do túnel.

## Endpoints adicionais

| Endpoint | Resposta | Falha |
|---|---|---|
| `GET /` | a página | — |
| `GET /v1/fleet` | `{"robots": [{"robot_id", "role", "nav_state", "last_error", "pose": {"x", "y", "yaw", "valid"}}]}`, com a sanitização do ticket 15 (`last_error` só códigos do contrato ou `NAV_ERROR`; `role` identificador ou `UNKNOWN`) | `503 {"error": "fleet_unavailable", "message": ...}` com texto fixo |
| `GET /v1/map` | `{"available", "resolution", "origin_x", "origin_y", "width", "height", "places": [{"name", "x", "y"}]}` | `available: false` sem mapa; `503 fleet_unavailable` |
| `GET /v1/map/image.png` | bytes PNG validados, `Cache-Control: max-age=300` | `404 map_unavailable` |
| `GET /v1/missions?limit=20` | as mais recentes primeiro: `mission_id`, `status`, `instruction`, `robot_id`, `planner`, `created_at`, `finished_at` (sem passos; `limit` de 1 a 50) | `422` para `limit` inválido |
| SimFleet `GET /api/map` | formato do Fleet UI, com o PNG do cenário | — |

Os endpoints de leitura não contam no limite de taxa de missões. Nenhum contrato existente muda: `POST` e `GET /v1/missions/{id}`, `/health` e as rotas do SimFleet continuam iguais. A única extensão do contrato de frota é o `GET /api/map` opcional; ela entra na suíte de contrato dos dois adaptadores e numa nota do ADR-0005.

## Critérios de aceitação

- [x] `GET /` serve a página com o CSP e os cabeçalhos acima; nenhum recurso externo é carregado
- [x] O mapa do warehouse aparece com obstáculos, os 7 lugares nomeados e os 3 robôs nas posições reais
- [x] As posições e os estados são atualizados a cada 1 s, sem recarregar a página
- [x] Um comando em português pelo campo vira `POST /v1/missions`; a missão aparece com status, passos e texto final, e o robô se move no mapa
- [x] Os status `completed`, `not_understood`, `incomplete`, `failed` e `rejected`, e as recusas `422`, `429` (com `Retry-After`) e `503`, aparecem com texto claro
- [x] O painel de saúde mostra a API (`/health/live`), o backend (`/health`: `ok` ou `degraded`), o adaptador, o planejador e `llm_enabled: false`
- [x] Com o backend fora do ar, a página continua de pé, mostra "backend indisponível", marca as posições como desatualizadas e mantém o histórico de missões
- [x] Sem conexão com o Fleet AI, a página mostra "sem conexão" e se recupera sozinha quando a conexão volta
- [x] Um texto da API com HTML (por exemplo, `<img src=x onerror=alert(1)>` na instrução) aparece como texto, nunca como marcação
- [x] O navegador nunca chama o SimFleet: todos os pedidos vão para a origem do Fleet AI
- [x] Funciona com o adaptador `fleet_ui` sem mapa (grade simples), sem erro na página
- [x] `scripts/demo.sh` sobe tudo em `127.0.0.1` e imprime o comando do túnel; README com o roteiro
- [x] Nenhuma dependência nova de runtime além do que já está no projeto; nenhum LLM, SDK ou serviço adicional
- [x] **Conversão de coordenadas:** o canvas converte metros em pixels com `resolution`, `origin_x`, `origin_y`, `width` e `height`, com o eixo y do mundo para cima e o do PNG para baixo, e a orientação do robô (`yaw` em radianos, anti-horário a partir de +x no mundo) desenhada com o sinal certo no canvas. Testado com pontos conhecidos (origem, cantos, um lugar nomeado), os limites do mapa e posições fora dele (marcadas como fora do mapa, sem quebrar o desenho)
- [x] **Histórico:** `GET /v1/missions` inclui missões ativas (`running`) e encerradas, em ordem de criação decrescente, sem mudar as regras de retenção (ticket 14); os detalhes continuam só em `GET /v1/missions/{mission_id}`
- [x] **Leituras validadas:** os endpoints novos validam e sanitizam o que vem do backend (corpo fora do contrato vira `503` com texto fixo), nunca devolvem mensagem de exceção bruta, limitam o tamanho dos payloads (mapa até 8 MB decodificado e dimensões até 4096 x 4096 px; até 100 robôs; textos de identificador até 64 caracteres) e validam o PNG com segurança (assinatura, cabeçalho `IHDR` coerente com `width` e `height`, base64 estrito, decodificação limitada, sem carregar a imagem inteira antes de conferir o tamanho)
- [x] **Só local:** a interface e a API ficam em `127.0.0.1`; o ticket não configura bind público, proxy externo nem exposição do SimFleet (o `scripts/demo.sh` usa `--host 127.0.0.1` nos dois serviços)
- [x] **Sem dependências externas no frontend:** nenhum CDN, script externo, fonte remota ou biblioteca paga; os arquivos estáticos ficam no repositório

## Testes previstos

Seam: API HTTP do Fleet AI em processo, com SimFleet e fake do Fleet UI em processo e transportes de teste (backend fora do ar, corpo fora do contrato, PNG inválido). O JavaScript não tem testes automatizados nesta versão: não há Node na VPS e o ticket não acrescenta serviços. Ele é coberto por verificações estáticas e pelo roteiro manual.

| Garantia | Teste |
|---|---|
| Página e cabeçalhos | `test_index_is_served_with_a_strict_content_security_policy` |
| Sem recursos externos | `test_web_assets_load_nothing_from_other_origins` (nenhum `http://`, `https://` ou `//` nos arquivos estáticos) |
| Sem HTML não confiável | `test_web_script_never_renders_api_text_as_html` (o `app.js` não usa `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval` nem `new Function`) |
| Estado da frota | `test_fleet_view_lists_robots_with_poses_and_states` (SimFleet; os dois adaptadores) |
| Sanitização da frota | `test_fleet_view_sanitizes_backend_text` (`last_error` e `role` com URL interna, token fictício e stack trace) |
| Backend fora do ar | `test_fleet_view_is_unavailable_without_leaking_details` (`503` com texto fixo) |
| Mapa | `test_map_view_has_geometry_and_named_places` (0,03 m/px, origem e 7 lugares do warehouse) |
| Imagem do mapa | `test_map_image_is_the_scenario_png` (bytes iguais ao PNG do cenário, `image/png`, `nosniff`) |
| Mapa ausente ou inválido | `test_map_is_unavailable_when_missing_or_invalid` (Fleet UI sem mapa, base64 inválido, PNG falso, tamanho acima do limite) |
| Contrato do mapa | `test_map_endpoint_matches_the_fleet_ui_format` (suíte de contrato: SimFleet e fake do Fleet UI) |
| Lista de missões | `test_missions_list_newest_first_without_steps` (com `limit` e `422` para valor inválido) |
| Leitura sem cota | `test_read_endpoints_do_not_use_the_mission_rate_limit` |
| Contratos intactos | a suíte existente continua passando sem mudanças nas asserções |
| Conversão de coordenadas | `test_world_to_pixel_known_points` (origem, cantos, doca de carga), `test_world_to_pixel_limits_and_outside_points`, `test_heading_rotation_on_the_canvas` (yaw 0, π/2, π, −π/2): as funções puras de `geometry.js` executadas por um interpretador de JavaScript embutido, só de desenvolvimento |
| Histórico com missões ativas | `test_missions_list_includes_running_and_finished_newest_first` (e a retenção do ticket 14 intacta) |
| Payloads limitados | `test_read_endpoints_reject_oversized_or_malformed_backend_bodies` (mapa acima de 8 MB, dimensões acima de 4096, `IHDR` divergente, base64 não estrito, mais de 100 robôs, id acima de 64 caracteres) |
| Só local | `test_demo_script_binds_only_to_localhost` (nenhum `0.0.0.0` ou host público no `scripts/demo.sh`) |

**Roteiro manual de aceitação pelo navegador** (pelo túnel; registrado no README):

1. Subir com `scripts/demo.sh` e abrir o túnel; abrir `http://localhost:8000/`.
2. Ver o mapa do warehouse com obstáculos e os 7 lugares; ver tb1, tb2 e tb3 nas posições iniciais, com estado e orientação.
3. Enviar "leve o tb1 até a doca de carga"; acompanhar o tb1 andando no mapa e os passos aparecendo; ver `completed` com o texto final.
4. Testar uma missão incompleta: enviar "leve o tb2 até a sala noroeste" e, durante a navegação, observar o resultado `incomplete` ao estourar o tempo máximo (ou reiniciar com `FLEET_AI_MISSION_TIMEOUT=5`), com o texto do cancelamento.
5. Enviar uma instrução com HTML (`<img src=x onerror=alert(1)>`) e ver o texto literal, sem alerta.
6. Simular backend indisponível: parar o SimFleet; ver "backend indisponível", posições marcadas como desatualizadas e o histórico ainda visível.
7. Subir o SimFleet de novo e confirmar que a página se recupera sozinha.
8. Na aba de rede do navegador, confirmar que só há pedidos para `localhost:8000`, sem nenhuma origem externa.

## Decisões para revisar

- **D1. Onde o mapa nasce:** `GET /api/map` no SimFleet, no formato do Fleet UI (recomendado), em vez de o Fleet AI ler o PNG do disco (isso acopla os dois processos ao mesmo sistema de arquivos e quebra no Compose).
- **D2. SPEC-003:** abrir a pasta `spec-003-interface-web` com este ticket, sem uma SPEC longa por enquanto (recomendado), em vez de ampliar o escopo da SPEC-001.
- **D3. Cache do `/v1/fleet`:** sem cache nesta versão local (cada aba gera uma leitura do backend por segundo). Antes da exposição pública, rever junto com o ticket 15.

## Comments

- 2026-10-28 (implementação), **mudança na forma de testar a geometria**: o plano era executar as funções puras de `geometry.js` num interpretador de JavaScript embutido, só de desenvolvimento. A instalação desse pacote foi bloqueada pela política de permissões (código externo), e não há Node na VPS. A conversão metros → pixels e a orientação ficaram em `src/fleet_ai/geometry.py`: `/v1/fleet` e `/v1/map` já devolvem `pixel` (`x`, `y`, `inside`) e `heading` (ângulo de canvas, `−yaw`), e o JavaScript só desenha. Os testes previstos de conversão (pontos conhecidos, cantos, fora do mapa e rotação) rodam pela API.
- **Notas e riscos restantes:**
  - O JavaScript não é executado nos testes automatizados; o desenho do canvas, o polling, o recuo e as mensagens são cobertos pelo roteiro manual e pelas verificações estáticas (sem `innerHTML`, `eval`, scripts inline ou origens externas).
  - Sem mapa no backend (Fleet UI sem SLAM), o Fleet AI monta uma moldura sintética em volta dos lugares e das posições dos robôs no momento da primeira leitura; um robô que sair dela aparece como "fora do mapa".
  - O mapa fica em cache por 5 minutos no Fleet AI; um mapa SLAM que mude depois disso demora até 5 minutos para aparecer.
  - `/v1/fleet` não tem cache (D3): cada aba aberta faz uma leitura do backend por segundo.
  - Os passos da missão ainda podem mostrar a mensagem bruta de uma recusa; é o ticket 15, pré-requisito da exposição pública.
