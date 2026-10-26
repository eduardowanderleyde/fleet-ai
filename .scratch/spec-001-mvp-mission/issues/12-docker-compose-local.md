# 12: Docker Compose local com os dois serviços

**What to build:** Fleet AI e SimFleet sobem juntos com Docker Compose na máquina local, do jeito que vão rodar na VPS: imagens próprias, usuário não-root, healthchecks, limite de memória, SimFleet só na rede interna e Fleet AI publicado apenas em `127.0.0.1`. Uma missão com o LLM roteirizado funciona dentro do Compose. Não há deploy.

**Blocked by:** 08, 09, 10, 11

**Status:** ready-for-agent

- [ ] Duas imagens com usuário não-root e sistema de arquivos somente leitura, exceto o volume do livro de uso
- [ ] Healthchecks dos dois serviços usam os endpoints `/health`; o Fleet AI só sobe depois do SimFleet saudável
- [ ] SimFleet sem porta publicada; Fleet AI publicado em `127.0.0.1` e porta configurável
- [ ] Limites de memória definidos; o SimFleet com o warehouse fica abaixo de 256 MB
- [ ] Livro de uso em volume nomeado, sobrevivendo a recriar os containers
- [ ] Segredos só por arquivo de ambiente não versionado
- [ ] Roteiro documentado de verificação: subir, criar uma missão com o adaptador roteirizado, ver `completed`, derrubar
