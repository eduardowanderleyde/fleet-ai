# 07: Tabela completa de intenções em português e inglês

**What to build:** O planejador determinístico passa a entender todas as intenções do MVP nos dois idiomas: listar robôs, estado de um robô, mover até lugar nomeado, mover até coordenada (com yaw opcional em graus) e cancelar. Robôs são reconhecidos por id ou apelido e lugares por nome ou sinônimo, sem diferença de maiúsculas ou acentos. A tabela de casos de teste é o documento vivo do que o sistema entende.

**Blocked by:** 06

**Status:** resolved

- [x] Tabela de casos verificada pela API de missões, com ao menos 4 instruções por intenção em cada idioma (40+ casos), cobrindo apelidos, sinônimos, acentos, maiúsculas e vírgula decimal
- [x] Coordenadas: "x 3,5 y -1", "(2, 4)", "to 2.0, 4.0 facing 90"; yaw em graus na instrução vira radianos no `move_robot`
- [x] Idioma detectado por instrução; texto final no mesmo idioma; indefinido usa inglês
- [x] Robô ou lugar desconhecido → `not_understood` com os nomes válidos do cenário
- [x] Duas intenções na mesma instrução ("vá até A e depois até B") → `not_understood` explicando que só uma ação por missão é suportada
- [x] Mesma instrução produz sempre o mesmo plano (determinismo verificado repetindo os casos)
- [x] Os exemplos devolvidos em `not_understood` são todos entendidos pelo próprio planejador (teste dedicado)
- [x] Intenção cancelar: o texto final só afirma que a navegação foi cancelada com resultado `confirmed`; com `ambiguous` diz que o robô parou sem afirmar a causa; com `not_confirmed` diz que o robô continua navegando; com `CANCEL_FAILED` diz que não havia navegação ativa (testes `test_cancel_text_reflects_confirmed`, `..._ambiguous`, `..._not_confirmed`, `..._without_active_navigation`, nos dois idiomas)

## Comments

- 2026-10-26 (ticket 06): a detecção de idioma conta palavras-marcadoras; `_PT_WORDS` inclui "o" e "a", e "a" também é artigo em inglês ("send tb2 to a dock" pesa para o português). Revisar a lista ao montar a tabela de casos nos dois idiomas.

- 2026-10-27 (implementação): os testes de texto do cancelamento ficaram num único teste parametrizado, `test_cancel_text_reflects_the_cancellation_outcome` (`confirmed`, `ambiguous`, `not_confirmed`, nos dois idiomas), e o caso sem navegação ativa (`CANCEL_FAILED`) está na tabela, nos dois idiomas. Mesma cobertura dos nomes previstos.
- 2026-10-27, **riscos restantes**: (1) instrução em português sem nenhum marcador ("faça um café") é tratada como inglês, conforme a SPEC-001, e a resposta sai em inglês; (2) "depois" sozinho conta como sequência, então "leve o tb1 até a doca depois" é recusado como duas ações (conservador, nada errado é executado); (3) os verbos das intenções (`planning.py`) e os marcadores de idioma (`language.py`) são listas separadas, e um verbo novo numa só pode mudar a detecção de idioma, o que a tabela tende a pegar; (4) `(2,5)` entre parênteses é x = 2, y = 5 (documentado na SPEC-001); (5) o escopo de robô (`robot_id` do pedido) ainda é ignorado pelo planejador, e é do ticket 08.
