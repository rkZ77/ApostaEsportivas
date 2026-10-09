"""Bilhete pessoal · a aposta que o usuario montou no Raio-X e quer acompanhar.

O QUE E' (2026-10-06, pedido do usuario). A aba Jogos deixa montar um bilhete
com selecoes de varios jogos (mercado de time ou de jogador). Este modulo e' o
que faz esse bilhete entrar na banca como qualquer outro pick: ele vira uma
CARTELA (`bilhetes_pessoais`, mesmo formato de picks_multiplas: pernas num
JSONB `games`, `total_odd`, `result`, `profit`) e o lancamento na banca e' a
linha de sempre em `user_followed_picks`, com pick_type='pessoal'. Saldo,
Meus Picks, fechamento do mes e conquistas leem dali sem saber que e' pessoal.

O QUE NAO E'. Nao e' pick da IA: nao entra em `pick_sources`, entao fica fora
do placar publico, do ranking e da performance do motor. E so' o dono le'.

LIQUIDACAO. Perna a perna, com os numeros que o proprio site coleta:
`match_statistics` pros mercados de time e `player_match_stats` pros de
jogador. Nada roda agendado neste projeto (decisao do usuario de 01/08), entao
quem liquida e' a leitura: abrir a banca ou Meus Picks passa pelos bilhetes
pendentes daquele usuario (ver `liquidar_pendentes`). Mesma regra de casa de
aposta: uma perna RED derruba o bilhete na hora, mesmo com jogo por acontecer.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

PICK_TYPE = "pessoal"
MAX_PERNAS = 20
#: Depois disso sem numero do provedor, a perna e' anulada com motivo nomeado
#: em vez de ficar pendente pra sempre. Mesmo prazo pra jogo que nao terminou
#: (adiado, cancelado): a casa devolve, e aqui tambem.
DIAS_SEM_DADO = 3
_FIM = ("FT", "AET", "PEN")

#: Mercado de time -> como tirar o numero da linha de match_statistics.
#: `escopo` diz de quem: o jogo inteiro, ou so' o time da casa/fora.
_COLUNA = {
    "gols": "goals", "escanteios": "corners", "cartoes": "yellow_cards",
    "chutes_alvo": "shots_on", "faltas": "fouls",
    # 07/10: chutes (todos), impedimentos e defesas do goleiro · so' jogo todo.
    "chutes": "total_shots", "impedimentos": "offsides", "defesas": "goalkeeper_saves",
}
_MERCADOS_TIME = {
    **{m: ("jogo", c) for m, c in _COLUNA.items()},
    "gols_time": ("time", "goals"),
    "escanteios_time": ("time", "corners"),
    "cartoes_time": ("time", "yellow_cards"),
    # Desde 07/10 todo mercado tem o recorte "de quem" (os dois, casa, fora).
    "chutes_alvo_time": ("time", "shots_on"),
    "faltas_time": ("time", "fouls"),
    "chutes_time": ("time", "total_shots"),
    "impedimentos_time": ("time", "offsides"),
    "defesas_time": ("time", "goalkeeper_saves"),
}
#: Coluna do 1o tempo de cada contador (folha do 1o tempo). Faltas nao tem: o
#: provedor so' publica o total, entao mercado de faltas so' existe no jogo
#: inteiro. O 2o tempo e' total - 1o.
_COLUNA_1T = {"goals": "goals_ht", "corners": "corners_1h",
              "yellow_cards": "yellow_cards_1h", "shots_on": "shots_on_1h"}
PERIODOS = ("total", "1t", "2t")

#: Resultado final (1X2) e chance dupla (09/10, pedido do usuario). Escolha ->
#: desfechos que dao GREEN, pelo placar dos 90 minutos.
_ESCOLHAS_RESULTADO = {
    "1": {"1"}, "X": {"X"}, "2": {"2"},
    "1X": {"1", "X"}, "12": {"1", "2"}, "X2": {"X", "2"},
}

#: Estatistica de jogador -> coluna de player_match_stats.
_ESTAT_JOGADOR = {
    "chutes": "shots_total", "chutes_alvo": "shots_on", "gols": "goals_total",
    "assistencias": "assists", "faltas": "fouls_committed", "faltas_sofridas": "fouls_drawn",
    "desarmes": "tackles_total", "defesas": "saves", "amarelos": "cards_yellow",
    "passes": "passes_total", "dribles": "dribbles_success",
}


class PernaInvalida(ValueError):
    pass


def _int(v, campo):
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise PernaInvalida(f"{campo} invalido")
    if n <= 0:
        raise PernaInvalida(f"{campo} invalido")
    return n


def validar_pernas(pernas) -> list[dict]:
    """So' o que a liquidacao sabe conferir entra · o resto e' recusado.

    Recusar na entrada e' o que impede um bilhete de ficar pendente pra sempre
    por ter um mercado que ninguem sabe liquidar. A saida e' a perna LIMPA (so'
    campos conhecidos), que e' o que vai pro banco.
    """
    if not isinstance(pernas, list) or not pernas:
        raise PernaInvalida("bilhete sem selecao")
    if len(pernas) > MAX_PERNAS:
        raise PernaInvalida(f"no maximo {MAX_PERNAS} selecoes")
    limpas, vistas = [], set()
    for p in pernas:
        if not isinstance(p, dict):
            raise PernaInvalida("selecao invalida")
        base = {
            "fixture_id": _int(p.get("fixture_id"), "jogo"),
            "home_team_id": _int(p.get("home_team_id"), "time da casa"),
            "away_team_id": _int(p.get("away_team_id"), "time de fora"),
            "home": str(p.get("home") or "")[:80],
            "away": str(p.get("away") or "")[:80],
            "descricao": str(p.get("descricao") or "")[:160],
        }
        # Odd da casa quando a selecao entrou no bilhete (07/10). Opcional, e
        # so' entra se for um numero de odd: e' ela que deixa recalcular o
        # bilhete quando uma perna e' anulada.
        try:
            odd_perna = float(p.get("odd")) if p.get("odd") is not None else None
        except (TypeError, ValueError):
            odd_perna = None
        if odd_perna is not None and 1.01 <= odd_perna <= 1000:
            base["odd"] = round(odd_perna, 2)
        tipo = p.get("tipo")
        if tipo == "time":
            mercado = p.get("mercado")
            if mercado == "btts":
                perna = {**base, "tipo": "time", "mercado": "btts"}
            elif mercado == "resultado":
                escolha = str(p.get("escolha") or "").upper()
                if escolha not in _ESCOLHAS_RESULTADO:
                    raise PernaInvalida("resultado invalido")
                perna = {**base, "tipo": "time", "mercado": "resultado", "escolha": escolha}
            elif mercado in _MERCADOS_TIME:
                direcao = p.get("direcao")
                if direcao not in ("mais", "menos"):
                    raise PernaInvalida("direcao invalida")
                try:
                    linha = float(p.get("linha"))
                except (TypeError, ValueError):
                    raise PernaInvalida("linha invalida")
                if not (0 < linha < 100):
                    raise PernaInvalida("linha invalida")
                periodo = p.get("periodo") or "total"
                if periodo not in PERIODOS:
                    raise PernaInvalida("tempo invalido")
                if periodo != "total" and _MERCADOS_TIME[mercado][1] not in _COLUNA_1T:
                    raise PernaInvalida("esse mercado so' existe no jogo inteiro")
                perna = {**base, "tipo": "time", "mercado": mercado,
                         "direcao": direcao, "linha": linha, "periodo": periodo}
                if _MERCADOS_TIME[mercado][0] == "time":
                    if p.get("lado_time") not in ("home", "away"):
                        raise PernaInvalida("time do mercado invalido")
                    perna["lado_time"] = p["lado_time"]
            else:
                raise PernaInvalida("mercado desconhecido")
        elif tipo == "jogador":
            estat = p.get("estat")
            if estat not in _ESTAT_JOGADOR:
                raise PernaInvalida("estatistica desconhecida")
            minimo = _int(p.get("minimo"), "minimo")
            perna = {**base, "tipo": "jogador", "estat": estat, "minimo": minimo,
                     "player_id": _int(p.get("player_id"), "jogador"),
                     "player_name": str(p.get("player_name") or "")[:80]}
        else:
            raise PernaInvalida("tipo de selecao desconhecido")
        chave = json.dumps({k: v for k, v in perna.items() if k != "descricao"}, sort_keys=True)
        if chave in vistas:
            continue   # a mesma selecao duas vezes nao e' bilhete melhor
        vistas.add(chave)
        limpas.append(perna)
    return limpas


# ── liquidacao (pura) ─────────────────────────────────────────────────────


def _valor_do_time(perna: dict, jogo: dict):
    if perna["mercado"] == "btts":
        hg, ag = jogo.get("home_goals"), jogo.get("away_goals")
        return None if hg is None or ag is None else (1 if hg > 0 and ag > 0 else 0)
    if perna["mercado"] == "resultado":
        # O placar, que e' o que a tela mostra ("Saiu 2-1").
        hg, ag = jogo.get("home_goals"), jogo.get("away_goals")
        return None if hg is None or ag is None else f"{hg}-{ag}"
    escopo, col = _MERCADOS_TIME[perna["mercado"]]
    periodo = perna.get("periodo") or "total"

    def lado(nome):
        total = jogo.get(f"{nome}_{col}")
        if periodo == "total":
            return total
        prim = jogo.get(f"{nome}_{_COLUNA_1T[col]}")
        if periodo == "1t":
            return prim
        return None if total is None or prim is None else total - prim

    casa, fora = lado("home"), lado("away")
    if escopo == "jogo":
        return None if casa is None or fora is None else casa + fora
    return casa if perna["lado_time"] == "home" else fora


def _decide(valor, direcao: str, linha: float) -> str:
    if valor == linha:
        return "VOID"   # linha cheia empatada: a casa devolve
    if direcao == "mais":
        return "GREEN" if valor > linha else "RED"
    return "GREEN" if valor < linha else "RED"


def liquidar_perna(perna: dict, jogo: dict | None, jogador: dict | None,
                   jogo_tem_fichas: bool, vencido: bool) -> tuple[str | None, object, str | None]:
    """(resultado, valor, motivo). resultado None = ainda pendente.

    `jogo`: a linha de match_statistics, ou None se nao ha'.
    `jogador`: a linha de player_match_stats daquele jogador naquele jogo.
    `jogo_tem_fichas`: o provedor publicou ficha de jogador desse jogo (sem
    isso, "nao achei o jogador" nao quer dizer "nao entrou").
    `vencido`: passou o prazo de espera (DIAS_SEM_DADO) desde o jogo/registro.
    """
    if not jogo or jogo.get("status") not in _FIM:
        return ("VOID", None, "jogo sem resultado") if vencido else (None, None, None)

    if perna["tipo"] == "time":
        valor = _valor_do_time(perna, jogo)
        if valor is None:
            return ("VOID", None, "sem estatistica do jogo") if vencido else (None, None, None)
        if perna["mercado"] == "btts":
            return ("GREEN" if valor else "RED"), valor, None
        if perna["mercado"] == "resultado":
            hg, ag = jogo["home_goals"], jogo["away_goals"]
            saiu = "1" if hg > ag else "2" if hg < ag else "X"
            return ("GREEN" if saiu in _ESCOLHAS_RESULTADO[perna["escolha"]] else "RED"), valor, None
        return _decide(valor, perna["direcao"], perna["linha"]), valor, None

    # jogador
    if jogador and (jogador.get("minutes") or 0) > 0:
        # O provedor manda null quando o lance nao aconteceu (0 chutes vem como
        # null, nao 0): com o jogador EM CAMPO, null e' zero.
        valor = jogador.get(_ESTAT_JOGADOR[perna["estat"]]) or 0
        return ("GREEN" if valor >= perna["minimo"] else "RED"), valor, None
    if jogo_tem_fichas:
        # Ha' ficha do jogo e ele nao esta' nela (ou ficou no banco): nao jogou.
        return "VOID", None, "jogador nao entrou em campo"
    return ("VOID", None, "sem estatistica de jogador") if vencido else (None, None, None)


def resultado_do_bilhete(resultados: list) -> str | None:
    """RED se qualquer perna perdeu (mesmo com outras pendentes, como na casa);
    senao pendente enquanto faltar perna; senao PUSH se tudo anulou; GREEN."""
    if "RED" in resultados:
        return "RED"
    if None in resultados:
        return None
    if all(r == "VOID" for r in resultados):
        return "PUSH"
    return "GREEN"


def odd_recalculada(pernas: list, odd_registrada: float) -> float | None:
    """A odd que a casa paga quando pernas sao anuladas: a registrada dividida
    pelas odds das anuladas. None se alguma anulada nao tem odd (nao da' pra
    saber) ou se o resultado nao faz sentido (abaixo de 1.01)."""
    anuladas = [p for p in pernas if p.get("resultado") == "VOID"]
    if not anuladas or any(not p.get("odd") for p in anuladas):
        return None
    divisor = 1.0
    for p in anuladas:
        divisor *= float(p["odd"])
    nova = round(odd_registrada / divisor, 2)
    return nova if nova >= 1.01 else None


#: Nome da familia no texto que o acompanhamento ao vivo (routers/live.py,
#: `_stat_for_market`) sabe ler, e o market_type que desempata.
_FAMILIA_AO_VIVO = {
    "gols": ("Gols", "goals"), "escanteios": ("Escanteios", "corners"),
    "cartoes": ("Cartões", "cards"), "chutes_alvo": ("Chutes no Alvo", "shots_on_target"),
    "faltas": ("Faltas", "fouls"),
    "chutes": ("Chutes", "shots"),
    "impedimentos": ("Impedimentos", "offsides"),
    "defesas": ("Defesas do Goleiro", "saves"),
}


def mercado_ao_vivo(perna: dict) -> tuple[str, str | None, str] | None:
    """(market, market_type, line) no formato dos picks da IA, pra a perna
    de TIME ser acompanhada ao vivo em Minhas Apostas pelo mesmo motor que
    acompanha o VIP. None pra perna de jogador: o feed ao vivo nao traz ficha
    de jogador, e ela so' tem numero quando o jogo acaba.

    E' so' a TELA: quem decide GREEN/RED continua sendo `liquidar_pendentes`,
    com match_statistics."""
    if perna.get("tipo") != "time":
        return None
    if perna["mercado"] == "btts":
        return "Ambas Marcam", "btts", "Sim"
    if perna["mercado"] == "resultado":
        # settlement.settle_outcome le "1", "X", "2", "1X", "12", "X2".
        nome = "Resultado Final" if len(perna["escolha"]) == 1 else "Dupla Chance"
        return nome, "result", perna["escolha"]
    base = perna["mercado"].removesuffix("_time")
    nome, mtype = _FAMILIA_AO_VIVO[base]
    if perna["mercado"].endswith("_time"):
        nome += " Casa" if perna.get("lado_time") == "home" else " Fora"
    periodo = perna.get("periodo") or "total"
    if periodo == "1t":
        nome += " 1º Tempo"
    elif periodo == "2t":
        nome += " 2º Tempo"
    linha = f"{'Over' if perna['direcao'] == 'mais' else 'Under'} {perna['linha']:g}"
    return nome, mtype, linha


# ── banco ─────────────────────────────────────────────────────────────────


def registrar(cur, user_id: int, pernas: list, stake_units: float,
              actual_odd: float, bet_house: str | None) -> int:
    """Cria o bilhete e o lanca na banca, na transacao de quem chama."""
    cur.execute("""
        INSERT INTO bilhetes_pessoais (user_id, games, total_odd)
        VALUES (%s, %s::jsonb, %s) RETURNING id
    """, (user_id, json.dumps(pernas, ensure_ascii=False), actual_odd))
    bilhete_id = cur.fetchone()["id"]
    cur.execute("""
        INSERT INTO user_followed_picks (user_id, pick_id, pick_type, stake_units,
                                         actual_odd, bet_house, unit_value)
        VALUES (%s, %s, %s, %s, %s, %s,
                (SELECT unit_value FROM user_banca WHERE user_id = %s))
    """, (user_id, bilhete_id, PICK_TYPE, stake_units, actual_odd, bet_house, user_id))
    return bilhete_id


def liquidar_pendentes(cur, user_id: int, agora: datetime | None = None) -> int:
    """Liquida os bilhetes pendentes do usuario. Devolve quantos fecharam.

    Tres consultas, qualquer que seja o numero de bilhetes: os pendentes, as
    linhas de jogo e as fichas de jogador, tudo por `= ANY`. Nao faz commit:
    quem chama decide (as rotas da banca comitam no fim).
    """
    agora = agora or datetime.utcnow()
    cur.execute("""
        SELECT id, games, created_at FROM bilhetes_pessoais
        WHERE user_id = %s AND result IS NULL
    """, (user_id,))
    bilhetes = [dict(r) for r in cur.fetchall()]
    if not bilhetes:
        return 0
    for b in bilhetes:
        if isinstance(b["games"], str):
            b["games"] = json.loads(b["games"])

    fixtures = sorted({p["fixture_id"] for b in bilhetes for p in b["games"]})
    cur.execute("""
        SELECT fixture_id, status, match_date,
               home_goals, away_goals, home_corners, away_corners,
               home_yellow_cards, away_yellow_cards, home_shots_on, away_shots_on,
               home_fouls, away_fouls,
               home_total_shots, away_total_shots, home_offsides, away_offsides,
               home_goalkeeper_saves, away_goalkeeper_saves,
               home_goals_ht, away_goals_ht, home_corners_1h, away_corners_1h,
               home_yellow_cards_1h, away_yellow_cards_1h, home_shots_on_1h, away_shots_on_1h
        FROM match_statistics WHERE fixture_id = ANY(%s)
    """, (fixtures,))
    jogos = {r["fixture_id"]: dict(r) for r in cur.fetchall()}

    jogadores = sorted({p["player_id"] for b in bilhetes for p in b["games"]
                        if p["tipo"] == "jogador"})
    fichas: dict = {}
    com_ficha: set = set()
    if jogadores:
        cur.execute(f"""
            SELECT fixture_id, player_id, minutes, {", ".join(sorted(set(_ESTAT_JOGADOR.values())))}
            FROM player_match_stats WHERE fixture_id = ANY(%s) AND player_id = ANY(%s)
        """, (fixtures, jogadores))
        fichas = {(r["fixture_id"], r["player_id"]): dict(r) for r in cur.fetchall()}
        cur.execute("SELECT DISTINCT fixture_id FROM player_match_stats WHERE fixture_id = ANY(%s)",
                    (fixtures,))
        com_ficha = {r["fixture_id"] for r in cur.fetchall()}

    fechados = 0
    for b in bilhetes:
        criado = b["created_at"] or agora
        resultados = []
        for p in b["games"]:
            jogo = jogos.get(p["fixture_id"])
            ref = jogo.get("match_date") if jogo and jogo.get("match_date") else criado
            if not isinstance(ref, datetime):
                ref = datetime.combine(ref, datetime.min.time())
            vencido = agora - max(ref, criado) > timedelta(days=DIAS_SEM_DADO)
            res, valor, motivo = liquidar_perna(
                p, jogo, fichas.get((p["fixture_id"], p.get("player_id"))),
                p["fixture_id"] in com_ficha, vencido)
            p["resultado"], p["valor"] = res, valor
            if motivo:
                p["motivo"] = motivo
            resultados.append(res)
        final = resultado_do_bilhete(resultados)
        observacao = None
        if final == "GREEN" and "VOID" in resultados:
            # A casa recalcula a odd sem a perna anulada. Com a odd de cada
            # perna anulada (gravada desde 07/10), a aposta passa a valer a odd
            # que a casa paga de fato; sem ela, fica a registrada e a tela avisa.
            cur.execute("""
                SELECT actual_odd FROM user_followed_picks
                 WHERE user_id = %s AND pick_id = %s AND pick_type = %s
            """, (user_id, b["id"], PICK_TYPE))
            lanc = cur.fetchone()
            nova = odd_recalculada(b["games"], float(lanc["actual_odd"])) if lanc and lanc["actual_odd"] else None
            if nova:
                cur.execute("""
                    UPDATE user_followed_picks SET actual_odd = %s
                     WHERE user_id = %s AND pick_id = %s AND pick_type = %s
                """, (nova, user_id, b["id"], PICK_TYPE))
                observacao = (f"Selecao anulada: a odd do bilhete foi recalculada "
                              f"de {float(lanc['actual_odd']):.2f} para {nova:.2f}, como a casa faz.")
            else:
                observacao = "Uma selecao foi anulada: a casa recalcula a odd do bilhete."
        cur.execute("""
            UPDATE bilhetes_pessoais
               SET games = %s::jsonb, result = %s, observacao = %s,
                   profit = CASE %s WHEN 'GREEN' THEN total_odd - 1
                                    WHEN 'RED' THEN -1 WHEN 'PUSH' THEN 0 END,
                   settled_at = CASE WHEN %s IS NULL THEN NULL ELSE NOW() END
             WHERE id = %s
        """, (json.dumps(b["games"], ensure_ascii=False), final, observacao,
              final, final, b["id"]))
        if final:
            fechados += 1
            # Avisa o dono: sino, celular e WhatsApp, com o dinheiro dele · o
            # mesmo aviso de qualquer pick seguido. Nunca propaga erro.
            from routers.notifications import notify_pick_result
            notify_pick_result(cur, b["id"], PICK_TYPE, final)
    return fechados


def liquidar_sem_quebrar(conn, cur, user_id: int) -> None:
    """Chamada das rotas de leitura: liquidar nunca pode derrubar a banca."""
    try:
        if liquidar_pendentes(cur, user_id):
            logger.info("[BILHETE] liquidados bilhetes do usuario %s", user_id)
        conn.commit()
    except Exception:
        logger.warning("[BILHETE] liquidacao falhou", exc_info=True)
        try:
            conn.rollback()
        except Exception:
            pass
