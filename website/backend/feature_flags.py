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

LIBERADO EM 12/09/2026 (decisão do usuário)
-------------------------------------------
A medição com dado de produção terminou e a flag virou para False: o produto
agora existe para todo mundo, com o MESMO corte de sempre. Vale repetir o que
o "todo mundo" quer dizer aqui, porque a flag não é o paywall:

  quem não assina    -> vê que a cartela existe, no teaser do paywall (mesmo
                        corte da múltipla, em suggestions.py);
  quem assina        -> vê a cartela inteira e pode seguir;
  quem não tem sessão-> vê o Bingo no placar público, já liquidado, com o peso
                        de 1u de `stake_plan.py` -- nunca as pernas.

O gate VIP de leitura e de follow nunca morou nesta flag: ele está em
`_FOLLOW_SO_VIP` (banca.py) e no paywall de `suggestions.py`, e continua de pé.
Esta constante respondia outra pergunta: "o produto já é do usuário?". Agora é.

PARA ESCONDER DE NOVO é uma linha (True aqui) mais o par do front,
`BINGO_BETA_ADMIN_ONLY` em `website/frontend/src/config.ts` -- os dois têm o
mesmo nome de propósito: par com nomes diferentes é par que sai de sincronia.
"""

#: Enquanto True, o Bingo do Dia só existe para quem tem plano admin.
#: False desde 12/09/2026: o teste com dado de produção acabou e o produto é
#: do usuário. O paywall VIP é outra coisa e não sai daqui (ver o topo).
BINGO_BETA_ADMIN_ONLY = False


def is_admin(user: dict | None) -> bool:
    return bool(user) and user.get("plan") == "admin"


def bingo_visivel(user: dict | None = None) -> bool:
    """O Bingo pode sair desta resposta?

    `user=None` é o caso do endpoint PÚBLICO (sem sessão). Enquanto o produto
    esteve em teste ele não via nada, nem no placar, nem na contagem do dia --
    um total que conta cartela invisível é pior do que não contar, porque o
    usuário soma os produtos da tela e não chega no número que o site mostra.
    Com a flag aberta ele passa a ver, e é o mesmo que já acontece com a
    múltipla: resultado liquidado e peso de 1u, sem as pernas.
    """
    return (not BINGO_BETA_ADMIN_ONLY) or is_admin(user)
