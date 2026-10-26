# 01: Esqueleto dos dois serviços com health e suíte verde

**What to build:** O repositório passa a ter os dois serviços (Fleet AI e SimFleet) subindo localmente, cada um respondendo `GET /health` com `{"status": "ok"}`, e um comando único que roda testes, lint e checagem de tipos, todos verdes. É o "walking skeleton": nenhuma regra de negócio, mas o caminho completo de projeto → serviço → teste HTTP em processo já funciona, e os próximos tickets só acrescentam comportamento.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Projeto Python 3.12 com dependências declaradas e travadas, sem instalar nada no sistema (ambiente virtual do projeto)
- [ ] `GET /health` do Fleet AI e do SimFleet respondem 200 com `{"status": "ok"}`, verificados por teste HTTP em processo (sem abrir porta)
- [ ] Um comando documentado roda testes, lint e checagem de tipos; os três passam
- [ ] Testes marcados como opt-in (API real) existem como categoria e ficam fora da execução padrão
- [ ] `.gitignore` cobre ambiente virtual, caches, `.env` e o arquivo do livro de uso
- [ ] README curto: o que é o projeto, como rodar os testes, link para a SPEC-001 e os ADRs
