"""Produto que já roda em produção, mas que ainda não é do usuário.

O BINGO DO DIA EM TESTE COM DADO REAL (09/09/2026, decisão do usuário)
----------------------------------------------------------------------
O produto está inteiro: motor, liquidação, banca, placar e tela. O que falta
é a medição -- e medir em dev não serve, porque dev vê 8 ligas e produção vê
14. Então ele roda em `main`, contra o banco de PROD, e o resultado só não
aparece para quem não é admin.

ISTO É UM GATE DE SERVIDOR, E ESSA É A DIFERENÇA
------------------------------------------------
Até aqui o Bingo era escondido por uma constante do FRONT (`BINGO_ENABLED` em
config.ts), e o comentário dela dizia por que isso bastava: em produção a
tabela `picks_bingo` estava VAZIA, então não havia o que esconder. A partir do
momento em que o motor publica cartela em produção, a premissa acabou -- um
`/api/suggestions/today` no DevTools entregaria a cartela inteira, com pernas,
mercados e odds, para qualquer assinante.

Por isso o corte mora aqui, no servidor, e o front só deixa de desenhar o que
o servidor não manda. As duas metades continuam existindo (a aba some, e o
dado não sai), mas nenhuma delas depende da outra para esconder.

COMO LIBERAR PARA TODO MUNDO
-----------------------------
Uma linha: `BINGO_BETA_ADMIN_ONLY = False`. Ela aparece no diff, que é
justamente o motivo de ser constante e não variável de ambiente (ver o
histórico de LIVE_PICKS_ENABLED em config.ts). O par do front é
`BINGO_BETA_ADMIN_ONLY` em `website/frontend/src/config.ts`, e os dois têm o
mesmo nome de propósito: par com nomes diferentes é par que sai de sincronia.
"""

#: Enquanto True, o Bingo do Dia só existe para quem tem plano admin.
BINGO_BETA_ADMIN_ONLY = True


def is_admin(user: dict | None) -> bool:
    return bool(user) and user.get("plan") == "admin"


def bingo_visivel(user: dict | None = None) -> bool:
    """O Bingo pode sair desta resposta?

    `user=None` é o caso do endpoint PÚBLICO (sem sessão): durante o teste ele
    nunca vê o produto, nem no placar, nem na contagem do dia. Um total que
    conta cartela invisível é pior do que não contar -- o usuário soma os
    produtos da tela e não chega no número que o site mostra.
    """
    return (not BINGO_BETA_ADMIN_ONLY) or is_admin(user)
