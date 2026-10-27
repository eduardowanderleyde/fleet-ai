# 07: Tabela completa de intenções em português e inglês

**What to build:** O planejador determinístico passa a entender todas as intenções do MVP nos dois idiomas: listar robôs, estado de um robô, mover até lugar nomeado, mover até coordenada (com yaw opcional em graus) e cancelar. Robôs são reconhecidos por id ou apelido e lugares por nome ou sinônimo, sem diferença de maiúsculas ou acentos. A tabela de casos de teste é o documento vivo do que o sistema entende.

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] Tabela de casos verificada pela API de missões, com ao menos 4 instruções por intenção em cada idioma (40+ casos), cobrindo apelidos, sinônimos, acentos, maiúsculas e vírgula decimal
- [ ] Coordenadas: "x 3,5 y -1", "(2, 4)", "to 2.0, 4.0 facing 90"; yaw em graus na instrução vira radianos no `move_robot`
- [ ] Idioma detectado por instrução; texto final no mesmo idioma; indefinido usa inglês
- [ ] Robô ou lugar desconhecido → `not_understood` com os nomes válidos do cenário
- [ ] Duas intenções na mesma instrução ("vá até A e depois até B") → `not_understood` explicando que só uma ação por missão é suportada
- [ ] Mesma instrução produz sempre o mesmo plano (determinismo verificado repetindo os casos)
- [ ] Os exemplos devolvidos em `not_understood` são todos entendidos pelo próprio planejador (teste dedicado)
- [ ] Intenção cancelar: o texto final só afirma que a navegação foi cancelada com resultado `confirmed`; com `ambiguous` diz que o robô parou sem afirmar a causa; com `not_confirmed` diz que o robô continua navegando; com `CANCEL_FAILED` diz que não havia navegação ativa (testes `test_cancel_text_reflects_confirmed`, `..._ambiguous`, `..._not_confirmed`, `..._without_active_navigation`, nos dois idiomas)

## Comments

- 2026-10-26 (ticket 06): a detecção de idioma conta palavras-marcadoras; `_PT_WORDS` inclui "o" e "a", e "a" também é artigo em inglês ("send tb2 to a dock" pesa para o português). Revisar a lista ao montar a tabela de casos nos dois idiomas.
