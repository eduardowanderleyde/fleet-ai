# 11: Seleção do adaptador de frota e health completo

**What to build:** O adaptador de frota (`sim` ou `fleet_ui`) e a URL do backend vêm da configuração; trocar de SimFleet para Fleet UI não exige mudar código. O `GET /health` do Fleet AI informa o adaptador de frota, se o backend responde e o adaptador de LLM. Um checklist manual documenta como validar contra o Fleet UI real.

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] `GET /health` → `{"status", "fleet_adapter", "fleet_backend_reachable", "llm_adapter"}`; backend fora do ar → `fleet_backend_reachable: false` e `status: "degraded"`, sem erro 500
- [ ] A suíte de missão (ticket 06) passa com o adaptador `fleet_ui` apontado para o fake do Fleet UI, sem alterar os testes
- [ ] Valor de adaptador desconhecido → o serviço não sobe, com mensagem clara
- [ ] Checklist manual no README: subir o Fleet UI real, apontar o Fleet AI, rodar uma missão com o adaptador real de LLM, e o aviso de que o Fleet UI não tem autenticação e só deve ser usado em rede confiável
