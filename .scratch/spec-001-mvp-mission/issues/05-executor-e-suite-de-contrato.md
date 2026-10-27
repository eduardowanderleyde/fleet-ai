# 05: Executor portado e suíte de contrato contra SimFleet e fake do Fleet UI

**What to build:** O Executor do `fleet-ui@a57a3b1` é portado (com a correção de pose por robô) para o subconjunto do MVP: listar robôs, status de um robô, mover, cancelar e a nova operação aguardar chegada. Uma única suíte de testes de contrato, parametrizada por backend, prova que o Executor obtém os mesmos resultados contra o SimFleet e contra um fake do Fleet UI construído a partir do código de referência.

**Blocked by:** 04

**Status:** ready-for-agent

- [ ] Código portado cita arquivo e commit de origem no `fleet-ui`; nenhum merge entre repositórios; aviso de licença do `fleet-ui` (MIT) preservado
- [ ] Status de um robô usa a pose de `poses[robot_id]`, com fallback para `pose`, como na referência
- [ ] Aguardar chegada faz polling do status até `nav_state` sair de `navigating` e devolve estado e pose finais; intervalo e timeout configuráveis; timeout vira erro do Executor
- [ ] Respostas HTTP ≥ 400 viram erro do Executor com a mensagem do backend (ex.: a recusa 403 de papel)
- [ ] A mesma suíte de contrato passa contra o SimFleet e contra o fake do Fleet UI: listar, status, mover até chegar, robô inexistente, papel sem movimento, destino inválido, cancelar
- [ ] O fake do Fleet UI documenta de quais endpoints e commit da referência os formatos foram tirados

## Comments

- 2026-10-26 (ticket 01): a suíte usa `httpx2` (o Starlette 1.10 depreciou `httpx` no `TestClient`) e `httpx` não está instalado. Portar o Executor já sobre `httpx2.AsyncClient`; o `ASGITransport` existe no `httpx2` 2.16.
