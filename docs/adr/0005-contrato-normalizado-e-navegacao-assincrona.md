# ADR-0005: Contrato de frota normalizado e navegação assíncrona

**Status:** aceito (2026-10-26); pontos em aberto decididos no mesmo dia (HTTP 409 e 422, validação de papel, correlação do cancelamento, resolução de planejamento, validação dupla de lugares)
**Altera:** ADR-0002 (o contrato deixa de copiar os formatos de resposta e erro do Fleet UI)

## Contexto

Lendo o `fleet-ui@a57a3b1` para implementar a navegação do SimFleet, apareceram
diferenças entre a SPEC-001 e o comportamento real do Fleet UI:

- O backend HTTP do Fleet UI chama os serviços ROS pelo `ros2 service call` e
  devolve `success` = "o comando terminou com código 0", não o sucesso da
  operação. O `message` é o texto bruto impresso pelo comando, com o
  `success`, a mensagem e o `error_code` reais do serviço dentro dele. Uma
  recusa do orquestrador chega como `{"success": true, ...}`.
- `go_to_point` com o robô já navegando é recusado (`ALREADY_NAVIGATING`).
- Destino inválido é aceito (`"Navigation started"`) e falha depois, de forma
  assíncrona, deixando o robô em `failed` com `last_error` igual a
  `NAV2_REJECTED` ou `NAV2_ABORTED`.
- `cancel` sem objetivo ativo responde `CANCEL_FAILED` ("No active goal").
- `last_error` guarda um código, não uma frase.
- Depois de um `cancel` aceito, o Nav2 pode concluir o objetivo como cancelado,
  e o orquestrador registra isso como `failed` / `NAV2_ABORTED`.

Copiar o formato bruto obrigaria o planejador a interpretar texto de terminal
ROS. Inventar semânticas diferentes no SimFleet faria um plano testado nele
quebrar no Fleet UI.

## Decisão

**Contrato normalizado.** Toda resposta de comando do contrato de frota é
`{"success": bool, "message": str, "error_code": str}`:

- `success` reflete a operação;
- `message` é texto legível em inglês, só para pessoas;
- `error_code` é vazio no sucesso e, na falha, um dos códigos do Fleet UI
  (tabela abaixo). Clientes decidem pelo `error_code`, nunca pelo `message`.

O SimFleet fala esse formato diretamente. **A tradução das respostas brutas do
Fleet UI acontece só no adaptador `fleet_ui` do Executor**, que extrai
`success`, `message` e `error_code` do texto do `ros2 service call` e das
recusas 403 do backend HTTP. O `fleet-ui` continua sem alterações. O formato de
`GET /api/status` e `GET /api/list_robots` não muda.

**Navegação assíncrona, como no Fleet UI.**

- Requisição malformada (`x`, `y` ou `yaw` ausente, não numérico, infinito ou
  NaN) é recusada na hora com HTTP 422 e `INVALID_REQUEST`.
- Robô desconhecido e papel sem movimento são recusados na hora com HTTP 403
  (`UNKNOWN_ROBOT`, `ROLE_NOT_ALLOWED`), como as recusas do backend do Fleet UI.
- Robô já navegando: recusa com `ALREADY_NAVIGATING` (HTTP 409). Um novo
  destino exige que o robô esteja fora de `navigating`; para interromper uma
  navegação, o cliente cancela antes.
- Destino bem formado é sempre aceito (`"Navigation started"`). Falhas de
  planejamento (destino ocupado, fora do mapa, sem caminho) aparecem na leitura
  seguinte do status como `nav_state: failed` e `last_error: NAV2_REJECTED`.
  `NAV2_ABORTED` fica reservado a falhas durante a execução.
- `cancel` sem objetivo ativo: `success: false`, `CANCEL_FAILED` (HTTP 409).
- **Cancelamento confirmado exige correlação**, nunca só o estado observado. O
  Executor só declara um cancelamento confirmado quando as três evidências
  existem: (1) ele mesmo enviou o destino ativo daquele robô e o viu em
  `navigating`; (2) o `cancel` para esse robô foi aceito; (3) a primeira leitura
  de status depois disso mostra `idle`. O resultado do cancelamento é um de:
  - `confirmed`: as três evidências;
  - `ambiguous`: `cancel` aceito, mas o robô aparece em `failed` (por exemplo,
    `NAV2_ABORTED`), ou o destino ativo não foi enviado por este Executor.
    O robô não está mais navegando, mas o Executor não afirma que foi o
    cancelamento que o parou;
  - `not_confirmed`: `cancel` aceito e o robô continua em `navigating` até o
    timeout.
  Um `NAV2_ABORTED` nunca é, sozinho, evidência de cancelamento.
- **Limitação do Fleet UI:** o status não identifica o objetivo (não há id de
  goal), e outros clientes, como a interface web do Fleet UI, podem enviar
  destinos ao mesmo robô. A correlação é por robô e pela ordem dos eventos que o
  próprio Executor observou. No Fleet UI, o orquestrador marca `idle` ao aceitar
  o cancelamento e pode trocar para `failed` / `NAV2_ABORTED` logo depois; por
  isso o resultado depende de qual estado a leitura pega, e `ambiguous` é um
  resultado legítimo, não um erro.
- A causa detalhada de cada falha (por exemplo, `target_occupied`,
  `target_out_of_map`, `no_path`) vai para um log estruturado do SimFleet, com
  robô e destino. Ela não faz parte do contrato.

| `error_code` | Quando | Resposta | Origem |
|---|---|---|---|
| `INVALID_REQUEST` | parâmetro ausente ou inválido | 422 | Fleet AI (o Fleet UI devolve o 422 padrão do FastAPI) |
| `UNKNOWN_ROBOT` | robô fora do cenário | 403 | Fleet UI (orquestrador e backend) |
| `ROLE_NOT_ALLOWED` | papel diferente de MUUT | 403 | Fleet UI (orquestrador e backend) |
| `ALREADY_NAVIGATING` | novo destino com navegação ativa | 409 | Fleet UI (orquestrador) |
| `CANCEL_FAILED` | cancelar sem objetivo ativo | 409 | Fleet UI (orquestrador) |
| `NAV2_REJECTED` | destino inválido, em `last_error` | — | Fleet UI (orquestrador) |
| `NAV2_ABORTED` | falha durante a execução, em `last_error` | — | Fleet UI (orquestrador) |

**SimFleet: decisões de simulação do MVP.**

- O papel de cada robô é validado ao carregar o cenário: só `MUUT`, `FUUT` ou
  `SU`.
- A\* 8-conectado numa **grade de planejamento** cuja resolução
  (`planning_resolution`, no cenário) é obrigatoriamente um múltiplo inteiro da
  resolução do mapa; um valor que não seja múltiplo impede o cenário de
  carregar. Sem o campo, usa-se o múltiplo mais próximo de 0,1 m. No warehouse
  (mapa de 0,03 m/px), 0,09 m.
- A redução é conservadora: uma célula de planejamento é bloqueada se qualquer
  pixel dela estiver bloqueado na grade inflada da resolução original. A célula
  de partida do robô é sempre considerada livre.
- Lugares nomeados são validados ao carregar nas duas grades, a inflada
  original e a de planejamento; um lugar bloqueado em qualquer uma delas impede
  o cenário de carregar.
- O caminho é suavizado por linha de visada, e cada segmento é validado contra
  a grade inflada da resolução original.
- Movimento cinemático: velocidade linear constante (0,3 m/s por padrão), yaw
  alinhado a cada segmento instantaneamente e yaw pedido assumido na chegada.
  Não é uma simulação física fiel.

## Considered Options

- **Copiar o formato bruto do Fleet UI no SimFleet:** máxima fidelidade, mas o
  planejador teria de interpretar texto de terminal ROS, e o defeito do
  `success` viraria parte do contrato.
- **Corrigir o Fleet UI:** fora de escopo (ADR-0001: o `fleet-ui` não é
  modificado).

## Consequences

- O adaptador `fleet_ui` tem lógica real (interpretação de texto) e precisa de
  testes próprios com respostas brutas reais; o fake do Fleet UI passa a emitir
  o formato bruto, não o normalizado.
- Planejadores tratam todos os backends do mesmo jeito: mover, aguardar o fim
  da navegação, ler o estado final.
- Planejadores relatam o resultado do cancelamento como ele é: `confirmed`,
  `ambiguous` ou `not_confirmed`. O texto final de uma missão nunca afirma que
  um cancelamento ocorreu sem o resultado `confirmed`.
- No SimFleet o cancelamento aceito sempre leva a `idle`, então o resultado é
  `confirmed` sempre que o destino ativo veio do mesmo Executor.
- Os HTTP 409 de `ALREADY_NAVIGATING` e `CANCEL_FAILED` são do contrato
  normalizado; no Fleet UI essas recusas chegam com HTTP 200, e o adaptador
  normaliza.
