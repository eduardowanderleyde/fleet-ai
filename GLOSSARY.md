# Glossário

| Termo | Definição | Evitar |
|---|---|---|
| **Missão** | Uma instrução em linguagem natural enviada ao Fleet AI, mais tudo o que foi feito para cumpri-la (passos, resultado). Tem um `mission_id`. | "job", "tarefa" (job é o termo do Fleet UI para record/replay) |
| **Passo** | Uma chamada de ferramenta feita durante a missão: nome, entrada (já com escopo aplicado) e resultado. | "step" na documentação em português |
| **Ferramenta** | Operação de alto nível que um planejador pode chamar (`list_robots`, `move_robot`...). Cada ferramenta corresponde a uma ou mais chamadas do contrato de frota. | "tool" na documentação em português |
| **Despachante** | Componente único que recebe nome e entrada de uma ferramenta, aplica o escopo de robô e chama o Executor. Usado pelos dois planejadores. | |
| **Planejador** | Quem transforma a instrução em passos. Porta com duas implementações: determinístico e LLM. | "agente" para o planejador determinístico |
| **Planejador determinístico** | Planejador padrão: reconhece intenções por regras, monta um plano fixo e o executa. Sem modelo de linguagem, sem rede, sem custo. | "IA", "agente" |
| **Planejador LLM** | O loop de tool use portado do Fleet UI (lá chamado Planner), atrás da porta de LLM. Desligado por padrão. | "Planner" sem qualificação |
| **Intenção** | Uma ação que o planejador determinístico sabe reconhecer: listar robôs, estado de um robô, mover até lugar nomeado, mover até coordenada, cancelar. | "comando" |
| **Lugar nomeado** | Ponto do cenário com nome e sinônimos em português e inglês (ex.: "doca de carga" / "loading dock"). Não faz parte do contrato de frota. | "waypoint" (no Fleet UI, waypoint é ponto de rota gravada) |
| **Apelido** | Nome alternativo de um robô no cenário ("robô 1", "robot one"). | |
| **Contrato de frota** | O subconjunto da API HTTP do Fleet UI que o Executor usa (status, lista de robôs, ir até um ponto, cancelar). Qualquer backend de frota precisa cumpri-lo com os mesmos formatos. | "API do robô" |
| **Backend de frota** | Um serviço que implementa o contrato de frota. Existem dois: SimFleet e Fleet UI. | |
| **Adaptador de frota** | A configuração que liga o Executor a um backend de frota (`sim` ou `fleet_ui`). | |
| **SimFleet** | Backend de frota 2D, sem ROS: robôs cinemáticos sobre um mapa de ocupação, com A* e relógio simulado. Não é evidência científica. | "simulador" sem qualificação (confunde com Gazebo) |
| **Fleet UI** | O sistema original com ROS 2, Nav2 e Gazebo ou robôs reais. Backend de frota para pesquisa. | |
| **Cenário** | Configuração lida pelo SimFleet e pelo Fleet AI: mapa, resolução, origem, robôs (id, papel, apelidos, pose inicial) e lugares nomeados. | "mundo" (termo do Gazebo) |
| **Papel** | Classe do robô herdada do Fleet UI. Só `MUUT` (móvel) aceita comando de movimento; `FUUT` e `SU` recusam. | |
| **Executor** | Cliente HTTP do contrato de frota. Única fronteira entre o Fleet AI e um backend de frota. | |
| **Escopo de robô** | Restrição opcional de uma missão a um único robô: o despachante reescreve à força o `robot_id` de todo comando. | |
| **Porta de LLM** | Interface que o planejador LLM usa para falar com um modelo. Na SPEC-001, só o LLM roteirizado a implementa. | |
| **LLM roteirizado** | Implementação de teste da porta de LLM que devolve uma sequência fixa de respostas. Não faz chamada de rede nem tem custo. | "mock do Claude" |
| **Analyst** | Leitor de resultados de campanhas do Fleet UI (`summary.json`). Fora da SPEC-001. | |
