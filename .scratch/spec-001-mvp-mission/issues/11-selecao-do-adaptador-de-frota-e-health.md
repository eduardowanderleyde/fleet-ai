# 11: Seleção do adaptador de frota e health completo

**What to build:** O adaptador de frota (`sim` ou `fleet_ui`) e a URL do backend vêm da configuração; trocar de SimFleet para Fleet UI não exige mudar código. O `GET /health` do Fleet AI informa o adaptador de frota, se o backend responde, o planejador ativo e que nenhum LLM real está habilitado. Um checklist manual documenta como validar contra o Fleet UI real.

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] `GET /health` → `{"status", "fleet_adapter", "fleet_backend_reachable", "planner", "llm_enabled"}`; com a configuração padrão, `planner: "deterministic"` e `llm_enabled: false`
- [ ] Backend fora do ar → `fleet_backend_reachable: false` e `status: "degraded"`, sem erro 500
- [ ] O teste de aceitação do ticket 06 passa com o adaptador `fleet_ui` apontado para o fake do Fleet UI, sem alterar o teste
- [ ] Valor de adaptador desconhecido → o serviço não sobe, com mensagem clara
- [ ] Checklist manual no README: subir o Fleet UI real, apontar o Fleet AI, rodar uma missão com o planejador determinístico, e o aviso de que o Fleet UI não tem autenticação e só deve ser usado em rede confiável
