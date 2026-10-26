# 09: Guardas de entrada, taxa por IP e concorrência

**What to build:** O Fleet AI recusa pedidos abusivos antes de planejar qualquer coisa: instrução vazia ou longa demais, mais missões por IP do que o permitido por minuto ou por dia, e mais missões simultâneas do que o limite global. As recusas têm códigos HTTP e corpo padronizados. A memória de missões tem teto.

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] Instrução vazia ou acima do limite (padrão 300 caracteres) → 422 `{"error", "message"}`, sem nenhum passo executado
- [ ] `robot_id` com formato inválido → 422
- [ ] Missão acima do limite por minuto do mesmo IP (padrão 10) → 429 com `Retry-After`; outro IP não é afetado
- [ ] Limite diário por IP (padrão 100) → 429
- [ ] Missão acima do limite de simultâneas (padrão 4) → 429; ao terminar uma missão, a vaga é liberada
- [ ] `X-Forwarded-For` só é considerado se a conexão vier de um proxy confiável configurado; sem isso, trocar o cabeçalho não escapa do limite
- [ ] Acima do teto de missões retidas (padrão 500), as mais antigas são descartadas; `GET` delas → 404
- [ ] Todos os limites vêm da configuração; os testes usam valores pequenos
