# Fleet AI

Orquestração de frotas de robôs móveis a partir de missões em linguagem
natural. Você escreve "leve o tb1 até a doca de carga" (ou "move tb1 to the
loading dock") e o Fleet AI transforma a instrução em chamadas HTTP de alto
nível a um backend de frota, nunca em comandos ROS 2 diretos.

**Funciona sem nenhuma chave de API.** O planejador padrão é determinístico,
por regras; não há LLM pago nem agente autônomo consumindo tokens. A integração
com modelos reais é uma funcionalidade futura, opcional e desligada por padrão
([ADR-0004](docs/adr/0004-planejador-deterministico-e-llm-opcional.md)).

> **Status: em implementação.** SPEC-001 (MVP), tickets 01 a 08 e 13 concluídos:
> `POST /v1/missions` aceita uma instrução como "leve o tb1 até a doca de carga",
> o planejador determinístico a executa no SimFleet e `GET /v1/missions/{id}`
> mostra passos e texto final. Toda missão termina (`completed`, `failed`,
> `incomplete` ou `not_understood`), mesmo com o backend fora do ar. O planejador
> entende, em português e inglês, listar robôs, estado de um robô, mover até um
> lugar ou coordenada e cancelar. Uma missão pode ser restrita a um robô e tem
> tempo máximo, com cancelamento verificado da navegação. Guardas de entrada vêm
> a seguir.

## Origem

O Fleet AI nasce da camada de agentes do
[Fleet UI](https://github.com/eduardowanderleyde/fleet-ui), ferramenta de
experimentos de repetibilidade em robótica móvel (ROS 2 Jazzy, Nav2, SLAM
Toolbox, TurtleBot4) desenvolvida no mestrado em Ciência da Computação no
CIn-UFPE. O Executor e o loop de tool use (Planner) de lá são a base daqui,
copiados e adaptados a partir de um commit de referência, num repositório
independente
([ADR-0001](docs/adr/0001-repositorio-independente-e-origem-do-codigo.md)).

## Arquitetura proposta

```
 missão em linguagem natural (PT ou EN)
            │
            ▼
┌──────────────────────────── Fleet AI (FastAPI) ────────────────────────────┐
│ API de missões ─► guardas (tamanho, taxa por IP, concorrência, tempo)      │
│        │                                                                   │
│        ▼                                                                   │
│  porta de planejador ─┬─► planejador determinístico (padrão, por regras)   │
│                       └─► planejador LLM (desligado por padrão)            │
│                                 └─► porta de LLM ─► LLM roteirizado (testes)│
│        │                                           └─► modelo real (futuro, │
│        ▼                                                opcional)          │
│  despachante de ferramentas + escopo de robô ─► Executor (cliente HTTP)    │
└───────────────────────────────────┬────────────────────────────────────────┘
                                    │  contrato de frota (HTTP)
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
        SimFleet (2D, sem ROS)          Fleet UI (ROS 2, Nav2, Gazebo
        mapa de ocupação, A*,           ou robôs reais)
        relógio simulado
```

- **Nunca fala com ROS.** O planejador decide *o quê* fazer; o Executor decide
  *como*, sempre pelo mesmo contrato HTTP.
- **Dois backends, um contrato.** O SimFleet roda em qualquer máquina e permite
  demo pública e testes de ponta a ponta; o Fleet UI é o backend de pesquisa.
  Trocar entre eles é configuração
  ([ADR-0002](docs/adr/0002-contrato-de-frota-e-dois-adaptadores.md)).
- **Dois planejadores, um formato de missão.** O determinístico entende um
  conjunto fechado de intenções (listar robôs, consultar estado, mover até um
  lugar nomeado ou coordenada, cancelar) em português e inglês. O planejador LLM
  mantém o loop agêntico do Fleet UI pronto e testado com um LLM roteirizado
  ([ADR-0003](docs/adr/0003-llm-roteirizado-nos-testes.md)).
- **Proteções desde o MVP.** Limites de tamanho de instrução, taxa por IP,
  missões simultâneas e tempo por missão.

O SimFleet é uma simulação 2D cinemática. Ele não substitui o Gazebo nem robôs
reais como evidência científica, e o planejador determinístico não é "IA": é
um reconhecedor de intenções por regras.

## Roadmap

| Spec | Escopo | Status |
|---|---|---|
| **SPEC-001** | MVP: missão em linguagem natural contra o SimFleet, planejador determinístico, contrato HTTP, guardas | Especificada, 12 tickets |
| SPEC-002 | Missões com várias ações e alocação entre robôs (cálculo de caminho, sem LLM) | Planejada |
| SPEC-003 | Streaming dos passos e interface web | Planejada |
| SPEC-004 | Servidor MCP com as mesmas ferramentas | Planejada |
| Futura | Integração opcional com modelos reais, com orçamento de tokens e custo, desligada por padrão | Opcional |

## Desenvolvimento

Requer apenas o [uv](https://docs.astral.sh/uv/); ele baixa o Python 3.12 e
instala as dependências travadas em `uv.lock` num ambiente virtual do projeto
(`.venv/`). Nenhuma chave de API é necessária.

```bash
uv sync                 # cria o ambiente
./scripts/check.sh      # lint, formatação, tipos e testes; tudo precisa passar
```

Subir os serviços localmente:

```bash
uv run uvicorn fleet_ai.app:create_app --factory --port 8000
uv run uvicorn simfleet.app:create_app --factory --port 8001
```

O SimFleet carrega o cenário indicado em `SIMFLEET_SCENARIO` (um arquivo
`scenario.toml`) ou, sem ela, o warehouse do Fleet UI, com tb1 e tb2 móveis
(MUUT), tb3 fixo (FUUT) e lugares nomeados como "doca de carga" e "corredor
central". Cenário inválido (mapa ausente, robô ou lugar em obstáculo, nome
repetido) impede o serviço de subir.

A navegação é cinemática e simplificada (MVP, ADR-0005): A* numa grade de
planejamento reduzida de forma conservadora (0,09 m no warehouse), caminho
suavizado sem tocar a área inflada dos obstáculos, velocidade constante
(0,3 m/s) e giro instantâneo. Não é uma simulação física fiel. O relógio
simulado pode ser acelerado com `SIMFLEET_TIME_SCALE`.

Comandos respondem `{"success", "message", "error_code"}`. Recusas imediatas:
`INVALID_REQUEST` (422), `UNKNOWN_ROBOT` e `ROLE_NOT_ALLOWED` (403),
`ALREADY_NAVIGATING` e `CANCEL_FAILED` (409). Destinos impossíveis são aceitos e
falham no status com `last_error: NAV2_REJECTED`; a causa (`target_occupied`,
`target_out_of_map`, `no_path`) vai para o log `simfleet.navigation`.

A suíte remove do ambiente qualquer variável `*_API_KEY` e falha se algum SDK de
LLM pago aparecer no `uv.lock`, inclusive como dependência indireta.

## Como o trabalho é organizado

Spec-Driven Development com TDD, usando as skills
[mattpocock-skills](https://github.com/mattpocock/skills) no Claude Code:
`/to-spec` → `/to-tickets` → `/implement`. O Claude Code é ferramenta de
desenvolvimento; o produto em si não depende de nenhum LLM.

- [`CLAUDE.md`](CLAUDE.md): regras do projeto para agentes
- [`GLOSSARY.md`](GLOSSARY.md): vocabulário do domínio
- [`docs/adr/`](docs/adr/): decisões de arquitetura
- [`.scratch/spec-001-mvp-mission/`](.scratch/spec-001-mvp-mission/): spec e tickets

## Licença

A definir.
