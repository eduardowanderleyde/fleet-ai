# 08: Guardas de entrada, taxa por IP e concorrência

**What to build:** O Fleet AI recusa pedidos abusivos antes de gastar qualquer token: instrução vazia ou longa demais, mais missões por IP do que o permitido por minuto ou por dia, e mais missões simultâneas do que o limite global. As recusas têm códigos HTTP e corpo padronizados.

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] Instrução vazia ou acima do limite (padrão 500 caracteres) → 422 `{"error", "message"}`, e o LLM roteirizado não recebe nenhuma chamada
- [ ] `robot_id` com formato inválido → 422
- [ ] Sexta missão do mesmo IP no mesmo minuto (padrão 5) → 429 com `Retry-After`; outro IP não é afetado
- [ ] Limite diário por IP (padrão 20) → 429
- [ ] Terceira missão simultânea (padrão 2) → 429; ao terminar uma missão, a vaga é liberada
- [ ] `X-Forwarded-For` só é considerado se a conexão vier de um proxy confiável configurado; sem isso, um cliente não consegue escapar do limite trocando o cabeçalho
- [ ] Todos os limites vêm da configuração; os testes usam valores pequenos
