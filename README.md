# Fleet AI

Orquestração por agentes de IA para frotas de robôs móveis. Você escreve uma
missão em linguagem natural ("leve o tb1 até a doca de carga") e um agente
baseado no Claude a executa chamando ferramentas HTTP de alto nível, nunca o
ROS 2 diretamente.

> **Status: especificação.** Ainda não há código. A SPEC-001 (MVP) e seus
> tickets estão aprovados; a implementação começa pelo ticket 01.

## Origem

O Fleet AI nasce da camada de agentes do
[Fleet UI](https://github.com/eduardowanderleyde/fleet-ui), ferramenta de
experimentos de repetibilidade em robótica móvel (ROS 2 Jazzy, Nav2, SLAM
Toolbox, TurtleBot4) desenvolvida no mestrado em Ciência da Computação no
CIn-UFPE. O Planner, o Executor e o Analyst de lá são a base daqui, copiados e
adaptados a partir de um commit de referência, num repositório independente
(ver [ADR-0001](docs/adr/0001-repositorio-independente-e-origem-do-codigo.md)).

## Arquitetura proposta

```
 missão em linguagem natural
            │
            ▼
┌─────────────────────────── Fleet AI (FastAPI) ───────────────────────────┐
│ API de missões ─► guardas (tamanho, taxa por IP, concorrência, orçamento)│
│        │                                                                 │
│        ▼                                                                 │
│     Planner ◄──► porta de LLM ──► Anthropic (produção)                   │
│        │                     └──► LLM roteirizado (testes, sem custo)    │
│        ▼                                                                 │
│   ferramentas ─► Executor (cliente HTTP do contrato de frota)            │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │  contrato de frota (HTTP)
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
     SimFleet (2D, sem ROS)          Fleet UI (ROS 2, Nav2, Gazebo
     mapa de ocupação, A*,           ou robôs reais)
     relógio simulado
```

- **O agente nunca fala com ROS.** Ele decide *o quê* fazer; o Executor decide
  *como*, sempre pelo mesmo contrato HTTP. Uma alucinação do modelo não tem como
  emitir comandos de baixo nível.
- **Dois backends, um contrato.** O SimFleet roda em qualquer máquina e permite
  demo pública e testes de ponta a ponta; o Fleet UI é o backend de pesquisa.
  Trocar entre eles é configuração
  ([ADR-0002](docs/adr/0002-contrato-de-frota-e-dois-adaptadores.md)).
- **Testes sem custo.** A suíte padrão usa um LLM roteirizado; chamadas à API
  real são opt-in ([ADR-0003](docs/adr/0003-llm-roteirizado-nos-testes.md)).
- **Proteções desde o MVP.** Limites de tamanho, taxa por IP, missões
  simultâneas, tokens e custo por missão e orçamento diário persistido.

O SimFleet é uma simulação 2D cinemática. Ele não substitui o Gazebo nem robôs
reais como evidência científica.

## Roadmap

| Spec | Escopo | Status |
|---|---|---|
| **SPEC-001** | MVP: missão em linguagem natural contra o SimFleet, com ferramentas de navegação, guardas e orçamento | Especificada, 12 tickets |
| SPEC-002 | Alocação de missões entre robôs (o LLM interpreta, o planejador de caminho otimiza) | Planejada |
| SPEC-003 | Streaming dos passos do agente e interface web | Planejada |
| SPEC-004 | Servidor MCP com as mesmas ferramentas | Planejada |
| SPEC-005 | Coordenação entre agentes | Planejada |

## Como o trabalho é organizado

Spec-Driven Development com TDD, usando as skills
[mattpocock-skills](https://github.com/mattpocock/skills) no Claude Code:
`/to-spec` → `/to-tickets` → `/implement`.

- [`CLAUDE.md`](CLAUDE.md): regras do projeto para agentes
- [`GLOSSARY.md`](GLOSSARY.md): vocabulário do domínio
- [`docs/adr/`](docs/adr/): decisões de arquitetura
- [`.scratch/spec-001-mvp-mission/`](.scratch/spec-001-mvp-mission/): spec e tickets

## Licença

A definir.
