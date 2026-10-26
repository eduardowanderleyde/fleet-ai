# 07: Escopo de robô e encerramento seguro do Planner

**What to build:** Uma missão pode ser restrita a um robô (`robot_id` no pedido): o `robot_id` de toda ferramenta é reescrito à força, mesmo que o modelo peça outro. Ao atingir o limite de turnos, a missão termina `incomplete` preservando os passos, em vez de lançar exceção. Erros inesperados fora das ferramentas terminam a missão em `failed` sem derrubar o serviço.

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] Missão com `robot_id: "tb1"` em que o roteiro pede `move_robot` no tb2: o passo registrado tem `robot_id: "tb1"`, o tb1 se move e o tb2 não
- [ ] `list_robots` numa missão com escopo continua listando a frota (só leitura); comandos ficam restritos ao robô do escopo
- [ ] Roteiro que nunca para de pedir ferramentas → `incomplete` após o limite configurado de turnos, com todos os passos executados preservados
- [ ] Falha do backend de frota fora de uma ferramenta (ex.: indisponível) → missão `failed` com mensagem; outras missões e o serviço seguem funcionando
- [ ] Tempo máximo de missão estourado → `incomplete`, e a navegação em curso é cancelada
