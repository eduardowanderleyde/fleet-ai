# 10: Planejador LLM com LLM roteirizado, desligado por padrão

**What to build:** O loop de tool use do `fleet-ui` é portado como segunda implementação da porta de planejador, dependendo de uma porta de LLM. A única implementação de LLM é o roteirizado. O planejador LLM só roda com configuração explícita; por padrão o serviço usa o determinístico. Assim o caminho agêntico fica testado e pronto para uma integração futura com modelos reais, sem nenhum custo agora.

**Blocked by:** 08

**Status:** ready-for-agent

- [ ] Porta de LLM definida (sistema, mensagens, ferramentas, limite de tokens → blocos, motivo de parada, uso); LLM roteirizado registra o que recebeu e falha alto se o roteiro acabar
- [ ] Planner portado cita arquivo e commit de origem; regras de sistema do `fleet-ui` mantidas, mais "aguardar chegada antes de declarar sucesso" e "responder no idioma da instrução"
- [ ] Com planejador `llm` e o roteiro `list_robots` → `get_robot_status` → `move_robot` → `wait_for_arrival` → texto, a missão termina `completed` com 4 passos, `planner: "llm"` e o tb1 no destino
- [ ] Erro de ferramenta volta ao modelo como `tool_result` com `is_error`
- [ ] Roteiro que nunca para de pedir ferramentas → `incomplete` após o limite de turnos, com os passos preservados
- [ ] Escopo de robô do ticket 08 vale também aqui (roteiro pede tb2, passo registra tb1)
- [ ] Configuração padrão → planejador determinístico; `llm` exige configuração explícita; adaptador de LLM diferente de `scripted` impede o serviço de subir

## Comments

- 2026-10-26 (ticket 06): o critério "despachante com as cinco ferramentas, nenhuma outra" do ticket 06 não é observável pela API com o planejador determinístico. Verificar aqui: as ferramentas que o LLM roteirizado recebe são exatamente `list_robots`, `get_robot_status`, `move_robot`, `wait_for_arrival`, `cancel_navigation`, e um `tool_use` com outro nome vira erro.
