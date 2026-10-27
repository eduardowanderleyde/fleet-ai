# Fleet AI

Orquestração de frotas de robôs móveis a partir de missões em linguagem natural,
executadas por ferramentas de alto nível sobre um backend de frota.

## Missões e planejamento

**Missão**:
Uma instrução em linguagem natural enviada ao Fleet AI, junto com tudo o que foi feito para cumpri-la e o resultado.
_Avoid_: job, tarefa (job é o termo do Fleet UI para gravação e reprodução de rotas)

**Passo**:
Uma chamada de ferramenta feita durante uma missão, com a entrada usada e o resultado obtido.
_Avoid_: step

**Ferramenta**:
Uma operação de alto nível sobre a frota que um planejador pode usar, como mover um robô ou cancelar sua navegação.
_Avoid_: tool, comando

**Planejador**:
Quem transforma a instrução de uma missão em passos.
_Avoid_: agente (quando se fala do planejador determinístico)

**Planejador determinístico**:
O planejador padrão: reconhece intenções por regras, sem modelo de linguagem.
_Avoid_: IA, agente

**Planejador LLM**:
O planejador que delega a escolha dos passos a um modelo de linguagem; desligado por padrão.
_Avoid_: Planner (sem qualificação)

**Intenção**:
Uma ação que o planejador determinístico sabe reconhecer numa instrução, como "mover até um lugar" ou "cancelar".
_Avoid_: comando

**Escopo de robô**:
A restrição de uma missão a um único robô, que nenhum passo pode contornar.

**Conflito de escopo**:
Uma instrução que cita um robô diferente do robô do escopo da missão; a missão é recusada em vez de executada no robô do escopo.

**LLM roteirizado**:
Um modelo de linguagem de mentira, que devolve respostas fixas, usado para testar o planejador LLM sem rede nem custo.
_Avoid_: mock do Claude

## Frota

**Robô**:
Uma unidade da frota, identificada por um id único no cenário, com um papel e uma pose.
_Avoid_: agente, unidade

**Papel**:
A classe de um robô herdada do Fleet UI; só robôs `MUUT` podem se mover, `FUUT` e `SU` são fixos.

**Apelido**:
Um nome alternativo de um robô, como "robô 1" ou "robot one".

**Pose**:
A posição (x, y) e a orientação (yaw) de um robô no plano do mapa.

**Destino**:
A pose para a qual um robô é mandado navegar.
_Avoid_: goal, objetivo, waypoint (no Fleet UI, waypoint é um ponto de rota gravada)

**Estado de navegação**:
Em que ponto da navegação um robô está: parado (`idle`), navegando (`navigating`) ou com a última navegação falhada (`failed`).
_Avoid_: status do robô (o status é a resposta inteira sobre a frota)

**Caminho**:
A sequência de pontos que o backend planeja para levar um robô da pose atual até o destino.
_Avoid_: rota, trajetória

**Trajetória**:
A sequência de poses que um robô de fato ocupou ao longo do tempo.
_Avoid_: caminho (o planejado), rota (a gravada no Fleet UI)

**Cancelamento confirmado**:
Um cancelamento que o Fleet AI pode afirmar que parou o robô, porque ligou o pedido aceito ao destino ativo que ele mesmo enviou e viu o robô parado logo em seguida.
_Avoid_: cancelamento aceito (aceitar o pedido não prova que o robô parou por causa dele)

**Cancelamento ambíguo**:
Um cancelamento aceito depois do qual o robô parou, mas sem evidência de que parou por causa dele.

**Grade de planejamento**:
A versão reduzida e conservadora do mapa sobre a qual o SimFleet calcula caminhos.
_Avoid_: mapa (o mapa é a imagem original)

**Código de erro**:
O identificador estável de por que um comando ou uma navegação falhou, compartilhado com o Fleet UI (por exemplo, `ALREADY_NAVIGATING`).
_Avoid_: mensagem de erro (a mensagem é só para pessoas)

## Backends

**Cenário**:
O mundo que o SimFleet simula e que o Fleet AI usa para entender nomes: o mapa, os robôs com seus papéis, apelidos e poses iniciais, e os lugares nomeados.
_Avoid_: mundo (termo do Gazebo)

**Lugar nomeado**:
Um ponto do cenário com nome e sinônimos em português e inglês, como "doca de carga" / "loading dock".
_Avoid_: waypoint, zona

**Contrato de frota**:
O conjunto de operações HTTP que todo backend de frota oferece, com respostas no mesmo formato.
_Avoid_: API do robô

**Backend de frota**:
Um serviço que cumpre o contrato de frota: o SimFleet ou o Fleet UI.

**Adaptador de frota**:
A peça do Fleet AI que conecta o Executor a um backend de frota específico e traduz as respostas dele para o contrato.
_Avoid_: driver, conector

**SimFleet**:
O backend de frota 2D e sem ROS, que move robôs cinemáticos sobre o mapa de um cenário; não é evidência científica.
_Avoid_: simulador (sem qualificação; confunde com o Gazebo)

**Fleet UI**:
O sistema original de pesquisa, com ROS 2, Nav2 e Gazebo ou robôs reais.

**Executor**:
A fronteira única do Fleet AI com um backend de frota: tudo o que um passo faz na frota passa por ele.

**Analyst**:
O leitor de resultados de campanhas do Fleet UI; fora da SPEC-001.
