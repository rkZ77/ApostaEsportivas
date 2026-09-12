"""O ADVERSARIO na projecao de uma prop de jogador (§8 do V2).

O QUE FALTAVA
-------------
`saves` sempre teve adversario -- e' o metodo em que ele e' o sinal FORTE
(correlacao 0.88 entre defesas do goleiro e chutes no alvo sofridos), e ele vem
pelo caminho medido do `goalkeeper_model`. Todo o resto do motor projetava o
jogador contra o vacuo: o mesmo atacante, com a mesma media, saia com a mesma
probabilidade contra o time que menos concede finalizacao da liga e contra o que
mais concede.

AQUI O ADVERSARIO E' AJUSTE, NAO SINAL
--------------------------------------
E' a diferenca que justifica este modulo existir separado do caminho de
`saves`. Chute de atacante e' majoritariamente do atacante; o adversario
desloca, nao define. Por isso:

  · o multiplicador e' RELATIVO A' LIGA (o time concede 1.18x a media da liga),
    e nao um nivel absoluto -- comparar contagem bruta entre ligas de ritmo
    diferente moveria a projecao por causa do campeonato, nao do adversario;

  · ele e' ENCOLHIDO pela amostra: seis jogos de um time nao sustentam um
    deslocamento de 20%, e a media da liga e' o alvo do encolhimento;

  · e ele e' LIMITADO. O ajuste maximo e' declarado, porque o erro da propria
    media do adversario cresce justamente nos extremos, onde ela seria mais
    tentadora.

CONCEDIDO E' O LADO OPOSTO
--------------------------
`match_statistics` guarda o que cada lado PRODUZIU (`home_total_shots` sao os
chutes do mandante). O que interessa aqui e' o que o adversario de hoje CONCEDE,
que e' a coluna do outro lado nos jogos dele. Confundir os dois inverte o
ajuste, e um ajuste invertido e' pior que ajuste nenhum -- e' por isso que o
lado nao e' inferido em lugar nenhum, ele e' montado aqui e so' aqui.

O MANDO ENTRA JUNTO
-------------------
O time concede em taxas diferentes jogando em casa e fora, e o pick e' sobre um
jogo com mando definido. E' o mesmo recorte que `volume_do_adversario` ja' fazia
pro caminho de `saves`, com a mesma justificativa escrita la'.
"""
from __future__ import annotations

#: Quantos jogos do adversario sao lidos. Mesmo teto do caminho de `saves`.
LIMITE_JOGOS = 10

#: Encolhimento: com `K` jogos o ajuste vale metade do que a media crua diria.
#: Oito e' a ordem de grandeza de meio returno -- abaixo disso o que se mede
#: ainda e' sequencia de tabela, nao propriedade do time.
K_ENCOLHIMENTO = 8

#: Teto do deslocamento, pros dois lados. 15% e' muito pra uma prop (desloca uma
#: media de 2.0 chutes pra 2.3) e pouco pra virar a decisao sozinho, que e'
#: exatamente o papel declarado no topo: ajuste, nao sinal.
AJUSTE_MAX = 0.15

#: Baseline de liga com menos que isto nao e' baseline, e' um punhado de jogos.
#: O ajuste inteiro fica de fora quando ele falta -- e' melhor projetar sem
#: adversario do que projetar contra uma referencia errada.
MIN_JOGOS_BASELINE = 20


#: Amostra minima do adversario pra o ajuste existir. Abaixo disso o motor nao
#: ajusta -- e registra que nao ajustou, que e' diferente de ajustar por 1.0 sem
#: dizer nada (§33).
MIN_JOGOS = 4


def _media_do_lado(cur, *, coluna: str, team_id: int | None, mando: str,
                   league_id, season, limite: int) -> tuple:
    """(media, amostra) da coluna do lado OPOSTO ao do time, no mando dado.

    `team_id` None devolve a media da LIGA inteira naquele mando -- e' o
    baseline contra o qual o adversario e' comparado, e ele precisa sair da
    mesma consulta pra nao comparar recortes diferentes (um filtrado por
    status/temporada e outro nao).
    """
    lado_time = "home" if mando == "home" else "away"
    lado_oposto = "away" if mando == "home" else "home"
    coluna_concedida = f"{lado_oposto}_{coluna}"

    filtros, params = [], []
    if team_id is not None:
        filtros.append(f"AND ms.{lado_time}_team_id = %s")
        params.append(team_id)
    if league_id and season:
        filtros.append("AND ms.league_id = %s AND ms.season = %s")
        params += [league_id, season]

    cur.execute(f"""
        SELECT ms.{coluna_concedida} AS valor
          FROM match_statistics ms
         WHERE ms.status IN ('FT','AET','PEN')
           AND ms.{coluna_concedida} IS NOT NULL
           {" ".join(filtros)}
      ORDER BY ms.match_date DESC
         LIMIT %s
    """, tuple(params) + (limite,))
    valores = [float(r["valor"] if isinstance(r, dict) else r[0]) for r in cur.fetchall()]
    if not valores:
        return (None, 0)
    return (round(sum(valores) / len(valores), 3), len(valores))


def avaliar(cur, metodo, *, adversario_id: int, mando_do_adversario: str,
            league_id, season) -> dict:
    """O quanto o adversario de hoje desloca a expectativa deste contador.

    Devolve SEMPRE um dicionario, com `disponivel` dizendo se houve dado. O
    caminho sem dado e' informacao pro `data_quality` e pro detector de
    contradicao -- nao um 1.0 silencioso.
    """
    coluna = getattr(metodo, "coluna_concedida", None)
    if not coluna:
        return {"disponivel": False, "motivo": "metodo sem coluna de adversario",
                "ajuste": None}

    media, amostra = _media_do_lado(
        cur, coluna=coluna, team_id=adversario_id, mando=mando_do_adversario,
        league_id=league_id, season=season, limite=LIMITE_JOGOS)
    if media is None or amostra < MIN_JOGOS:
        return {"disponivel": False, "motivo": "adversario sem jogos suficientes",
                "ajuste": None, "amostra": amostra}

    # Baseline da propria liga, no mesmo mando. Sem ele o motor compararia a
    # contagem do adversario com nada, e "1.4 chutes no alvo concedidos" nao
    # significa alto nem baixo fora do campeonato em que foi medido.
    #
    # 200 jogos e' teto de leitura, nao exigencia: o que vier menos vira
    # baseline mais fraco, e quem cobra isso e' `MIN_JOGOS_BASELINE` abaixo.
    baseline, n_baseline = _media_do_lado(
        cur, coluna=coluna, team_id=None, mando=mando_do_adversario,
        league_id=league_id, season=season, limite=200)
    if not baseline or baseline <= 0 or n_baseline < MIN_JOGOS_BASELINE:
        return {"disponivel": False, "motivo": "liga sem baseline suficiente",
                "ajuste": None, "media": media, "amostra": amostra,
                "baseline_amostra": n_baseline}

    razao_crua = media / baseline
    peso = amostra / (amostra + K_ENCOLHIMENTO)
    razao = 1.0 + (razao_crua - 1.0) * peso
    ajuste = round(min(max(razao, 1 - AJUSTE_MAX), 1 + AJUSTE_MAX), 4)
    return {
        "disponivel": True,
        "ajuste": ajuste,
        "media": media,
        "amostra": amostra,
        "baseline": baseline,
        "baseline_amostra": n_baseline,
        "razao_crua": round(razao_crua, 4),
        "peso_da_amostra": round(peso, 3),
        "limitado": abs(razao - 1.0) > AJUSTE_MAX,
        "mando": mando_do_adversario,
        "contador": coluna,
        "motivo": None,
    }


def matchup(metodo, ajuste: dict) -> dict:
    """Confronto individual (§9). Hoje ele NAO existe na base, e diz isso.

    O projeto nao tem dado de posicao media, de duelo por setor nem de marcador
    direto -- `player_match_stats` tem `duels_total`/`duels_won` do jogador, que
    e' agregado do jogo inteiro e nao diz contra QUEM. Inventar um matchup a
    partir disso seria exatamente o que o §9 proibe.

    O que existe e' o nivel do SETOR do adversario, que e' o `ajuste` acima.
    Entao o matchup sai `unavailable`, o motor desconta qualidade de dado por
    ele faltar (§9: "reduzir a confianca quando essa informacao for critica") e
    ninguem le' um numero que nao foi medido.
    """
    return {
        "disponivel": False,
        "motivo": "sem dado de confronto individual na base",
        "proxy_setorial": (ajuste or {}).get("ajuste"),
        "familia": metodo.slug,
    }
