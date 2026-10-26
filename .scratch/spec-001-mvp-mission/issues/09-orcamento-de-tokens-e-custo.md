# 09: Orçamento de tokens e custo, e livro de uso persistido

**What to build:** Cada missão tem tetos de tokens e de custo estimado, e o serviço tem um teto de custo diário global que sobrevive a reinícios. O custo é calculado a partir do uso devolvido pelo LLM e de uma tabela de preços por modelo vinda da configuração. O uso de cada missão fica gravado num livro de uso em SQLite e aparece na resposta da missão.

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] `usage` da missão traz `input_tokens`, `output_tokens` e `estimated_cost_usd` coerentes com o uso fictício do LLM roteirizado e a tabela de preços configurada
- [ ] Missão cujo próximo turno estouraria o teto de tokens ou de custo por missão → `incomplete` com motivo, sem fazer a chamada
- [ ] Teto diário atingido → novas missões recebem 503 `{"error": "daily_budget_exhausted", ...}`; o LLM não é chamado
- [ ] Missão em curso que atinge o teto diário entre turnos → `incomplete`
- [ ] Reiniciar o serviço (recriar a aplicação apontando para o mesmo livro) mantém o gasto do dia; no dia UTC seguinte o teto zera
- [ ] Modelo sem preço na tabela → o serviço recusa subir com mensagem clara
- [ ] Nenhum preço fixo no código
