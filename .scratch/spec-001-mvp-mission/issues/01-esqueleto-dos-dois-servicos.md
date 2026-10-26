# 01: Esqueleto dos dois serviços com health e suíte verde, sem LLM pago

**What to build:** O repositório passa a ter os dois serviços (Fleet AI e SimFleet) subindo localmente, cada um respondendo `GET /health` com `{"status": "ok"}`, e um comando único que roda testes, lint e checagem de tipos, todos verdes. É o "walking skeleton": nenhuma regra de negócio, mas o caminho completo de projeto → serviço → teste HTTP em processo já funciona. Desde o primeiro dia, o projeto sobe e testa sem nenhuma chave de API e sem SDK de LLM pago.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Projeto Python 3.12 com dependências declaradas e travadas, num ambiente virtual do projeto (nada instalado no sistema)
- [ ] `GET /health` do Fleet AI e do SimFleet respondem 200 com `{"status": "ok"}`, verificados por teste HTTP em processo (sem abrir porta)
- [ ] Um comando documentado roda testes, lint e checagem de tipos; os três passam
- [ ] Teste de custo zero: nenhuma dependência declarada é SDK de LLM pago (lista de nomes proibidos mantida no próprio teste) e a suíte roda com o ambiente sem nenhuma variável `*_API_KEY`
- [ ] README atualizado com o comando de testes
