# 14: Endurecimento das guardas: limpeza do limitador e retenção segura

**What to build:** Antes do deploy público, duas correções nas guardas do ticket 09 (SPEC-001, Guardas). (1) O limitador de taxa deixa de guardar IPs que só consultaram e remove de forma oportunista, com o relógio injetado, os registros com mais de 24 h, sem tarefa periódica e sem alterar os limites de quem ainda está nas janelas. (2) A retenção de missões passa a descartar só missões terminais: uma missão `running` nunca some do histórico, e quando a retenção estiver cheia sem missão terminal elegível para descarte, a criação é recusada com `503 capacity_exhausted`, sem criar missão, sem planejar e sem gastar cota. A admissão continua atômica no modelo de um processo com um event loop.

**Blocked by:** 09

**Status:** resolved

- [x] Consultar o limitador para um IP sem missão aceita não cria registro para ele
- [x] Registros com mais de 24 h somem nas próprias chamadas do limitador; um IP sem missão nas últimas 24 h deixa de ser guardado
- [x] A varredura completa dos IPs roda no máximo uma vez por minuto do relógio injetado
- [x] A limpeza preserva os limites: um IP com missões dentro da janela de 1 minuto ou de 24 h continua limitado depois de uma varredura
- [x] Acima do teto de retenção, sai a missão terminal mais antiga; missões `running` nunca são descartadas e continuam respondendo `GET` com 200
- [x] Retenção cheia sem missão terminal elegível → `503`, `{"error": "capacity_exhausted", "message"}`, com `Retry-After` (estimativa)
- [x] Uma criação recusada por capacidade não consome cota, não devolve `mission_id`, não cria missão e não inicia o planejador
- [x] Com várias criações simultâneas, o número de missões aceitas nunca passa da capacidade, e cada recusada cumpre o critério anterior
- [x] Nenhuma pausa assíncrona entre a primeira checagem de admissão e a inserção da missão (regra escrita no código, coberta pelo teste de criações simultâneas)
- [x] Sem propriedade pública nova de produção só para os testes: os testes do limitador observam o estado interno

## Testes previstos

Seams: API HTTP do Fleet AI em processo (SPEC-001), com planejadores de teste que seguram missões e contam chamadas; e o `RateLimiter` direto com relógio injetado (confirmado pelo dono em 2026-10-27), observando o estado interno nos testes, sem API pública nova.

| Critério | Teste |
|---|---|
| Consulta não cria registro | `test_querying_an_ip_does_not_track_it` (`RateLimiter`) |
| Expiração em 24 h | `test_ips_without_missions_in_the_last_day_are_forgotten` (`RateLimiter`) |
| Varredura no máximo por minuto | `test_sweep_runs_at_most_once_per_minute` (`RateLimiter`) |
| Limites preservados | `test_cleanup_preserves_minute_and_day_limits` (`RateLimiter`) e `test_rate_limits_still_hold_after_cleanup` (API) |
| Descarte só de terminais | `test_retention_drops_the_oldest_terminal_mission_and_keeps_running_ones` |
| Retenção esgotada | `test_creation_is_refused_when_no_terminal_mission_can_be_dropped` |
| Recusa sem efeitos | o teste anterior confere: sem `mission_id`, planejador não chamado, cota intacta (uma criação aceita depois, com cota de N, ainda é aceita) |
| Criações simultâneas | `test_concurrent_creations_never_exceed_the_retention_capacity` (N criações em paralelo com missões presas: aceitas = capacidade; recusadas sem `mission_id`, sem planejar, sem cota) |
| Invariante | `test_running_missions_never_disappear` (em cenários variados, nenhuma missão `running` responde 404) |

Cada garantia com prova de sanidade (desligar a regra e ver o teste falhar).

## Fora deste ticket

- Teto absoluto de IPs rastreados e limite de taxa bruto no proxy reverso: pré-requisitos do deploy público, registrados na SPEC-001 (Further Notes).
- Coordenação de limites entre processos ou réplicas.
- Política de `ExecutorTimeout` (ADR-0006, proposto).
- Orçamento de tokens e custos (ADR-0004).

## Comments

- 2026-10-27 (implementação): o `Retry-After` do `503 capacity_exhausted` é uma estimativa fixa de 5 s (`CAPACITY_RETRY_AFTER`), não garantia. Com os padrões (500 guardadas, 4 simultâneas) o 503 é inalcançável, porque o limite de concorrência recusa antes; ele aparece com `missions_retained` menor ou igual a `max_concurrent`. O teste de criações simultâneas cobre a admissão atômica: com um `await` inserido entre a checagem e a inserção, ele falha.
