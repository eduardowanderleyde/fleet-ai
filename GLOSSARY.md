# Glossário

| Termo | Definição | Evitar |
|---|---|---|
| **Missão** | Uma instrução em linguagem natural enviada ao Fleet AI, mais tudo o que o agente fez para cumpri-la (passos, uso, resultado). Tem um `mission_id`. | "job", "tarefa" (job é o termo do Fleet UI para record/replay) |
| **Passo** | Uma chamada de ferramenta feita pelo agente durante a missão: nome, entrada (já com escopo aplicado) e resultado. | "step" na documentação em português |
| **Ferramenta** | Operação de alto nível que o agente pode chamar (`list_robots`, `move_robot`...). Cada ferramenta corresponde a uma ou mais chamadas do contrato de frota. | "tool" na documentação em português |
| **Contrato de frota** | O subconjunto da API HTTP do Fleet UI que o Executor usa (status, lista de robôs, ir até um ponto, cancelar). Qualquer backend de frota precisa cumpri-lo com os mesmos formatos. | "API do robô" |
| **Backend de frota** | Um serviço que implementa o contrato de frota. Existem dois: SimFleet e Fleet UI. | |
| **Adaptador** | A configuração que liga o Executor a um backend de frota específico (`sim` ou `fleet_ui`). | |
| **SimFleet** | Backend de frota 2D, sem ROS: robôs cinemáticos sobre um mapa de ocupação, com A* e relógio simulado. Não é evidência científica. | "simulador" sem qualificação (confunde com Gazebo) |
| **Fleet UI** | O sistema original com ROS 2, Nav2 e Gazebo ou robôs reais. Backend de frota de produção para pesquisa. | |
| **Cenário** | Configuração do SimFleet: imagem do mapa, resolução, origem e robôs (id, papel, pose inicial). | "mundo" (termo do Gazebo) |
| **Papel** | Classe do robô herdada do Fleet UI. Só `MUUT` (móvel) aceita comando de movimento; `FUUT` e `SU` recusam. | |
| **Planner** | O loop de tool use que conversa com o LLM, despacha ferramentas e aplica o escopo. | "agente" quando se quer dizer o loop em si |
| **Executor** | Cliente HTTP do contrato de frota. Única fronteira entre o agente e um backend de frota. | |
| **Analyst** | Leitor de resultados de campanhas (`summary.json`). Fora da SPEC-001. | |
| **Escopo de robô** | Restrição opcional de uma missão a um único robô: o `robot_id` de toda ferramenta é reescrito à força para ele. | |
| **LLM roteirizado** | Implementação de teste da porta de LLM que devolve uma sequência fixa de respostas (texto e `tool_use`). Não faz chamada de rede. | "mock do Claude" |
| **Orçamento** | Limites de gasto: tokens e custo por missão, custo por dia. | |
| **Livro de uso** | Registro persistido de tokens e custo estimado por missão, base do orçamento diário. | |
