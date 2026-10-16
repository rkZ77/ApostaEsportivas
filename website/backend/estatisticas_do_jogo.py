"""Aba Estatisticas do Raio-X (15/10/2026, pedido do usuario: "estatistica do
jogo em tempo real igual SofaScore, e depois quando finaliza tambem").

A folha completa do jogo (posse, xG, chutes por tipo, escanteios, faltas,
cartoes, defesas, passes), lado a lado, no jogo inteiro, 1o e 2o tempo.

DE ONDE VEM, NA ORDEM, PRA NAO GASTAR COTA ("lembra dos gastos da API"):
  1. Jogo encerrado e ja' coletado: `match_statistics` (a coleta grava a folha
     cheia e o 1o tempo). Zero chamada.
  2. Jogo rolando: o cache de routers/live.py, que a lista de Jogos (a cada
     30s), a varredura dos picks e o placar do Raio-X ja' mantem quente.
     Zero chamada a mais.
  3. Cache frio ou velho (ninguem esta' aquecendo este jogo): UMA busca, que
     vale pra todo mundo pelo TTL do cache (live.py), e nunca com a cota do
     dia acima de TETO_DA_COTA_PCT.

Aqui so' a leitura e a montagem · as chamadas ficam em live.py.
"""
from __future__ import annotations

#: (tipo na folha da API-Football, chave, rotulo, eh_percentual)
ITENS = (
    ("Ball Possession",   "posse",            "Posse de bola",        True),
    ("expected_goals",    "xg",               "Gols esperados (xG)",  False),
    ("Total Shots",       "chutes",           "Finalizações",         False),
    ("Shots on Goal",     "chutes_no_gol",    "No gol",               False),
    ("Shots off Goal",    "chutes_fora",      "Para fora",            False),
    ("Blocked Shots",     "chutes_bloqueados", "Bloqueadas",          False),
    ("Shots insidebox",   "chutes_na_area",   "Dentro da área",       False),
    ("Shots outsidebox",  "chutes_de_fora",   "De fora da área",      False),
    ("Corner Kicks",      "escanteios",       "Escanteios",           False),
    ("Offsides",          "impedimentos",     "Impedimentos",         False),
    ("Fouls",             "faltas",           "Faltas",               False),
    ("Yellow Cards",      "amarelos",         "Cartões amarelos",     False),
    ("Red Cards",         "vermelhos",        "Cartões vermelhos",    False),
    ("Goalkeeper Saves",  "defesas",          "Defesas do goleiro",   False),
    ("Total passes",      "passes",           "Passes",               False),
    ("Passes %",          "passes_certos",    "Passes certos",        True),
)

#: Somam no jogo: o 2o tempo sai da folha cheia menos o 1o. Posse, xG e
#: percentual de passe nao somam, entao nao tem 2o tempo derivado.
_SOMAM = {"chutes", "chutes_no_gol", "chutes_fora", "chutes_bloqueados", "chutes_na_area",
          "chutes_de_fora", "escanteios", "impedimentos", "faltas", "amarelos", "vermelhos",
          "defesas", "passes"}

#: Coluna de `match_statistics` por chave (sem o prefixo home_/away_).
COLUNAS = {
    "posse": "possession", "xg": "xg", "chutes": "total_shots", "chutes_no_gol": "shots_on",
    "chutes_fora": "shots_off", "chutes_bloqueados": "blocked_shots",
    "chutes_na_area": "shots_insidebox", "chutes_de_fora": "shots_outsidebox",
    "escanteios": "corners", "impedimentos": "offsides", "faltas": "fouls",
    "amarelos": "yellow_cards", "vermelhos": "red_cards", "defesas": "goalkeeper_saves",
    "passes": "passes", "passes_certos": "passes_accuracy",
}
#: As do 1o tempo que a coleta grava (CONTADORES_1T do motor).
COLUNAS_1T = {"escanteios": "corners_1h", "amarelos": "yellow_cards_1h",
              "vermelhos": "red_cards_1h", "chutes_no_gol": "shots_on_1h",
              "chutes": "total_shots_1h"}

_POR_TIPO = {tipo: chave for tipo, chave, _, _ in ITENS}


def numero(valor):
    """'58%' -> 58, '1.34' -> 1.34, 7 -> 7, None/'' -> None."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        return valor
    try:
        t = str(valor).strip().rstrip("%")
        f = float(t)
        return int(f) if f.is_integer() and "." not in t else round(f, 2)
    except ValueError:
        return None


def folha_por_chave(itens: list | None, zerar_nulo: bool) -> dict:
    """{chave: valor} de uma lista `statistics` de um time.

    Com a bola rolando o provedor manda `null` quando o lance nao aconteceu
    ("0 impedimentos" vem null), e ai' e' zero mesmo (mesma regra da lista de
    Jogos). Tipo que nem veio fica de fora, nunca vira zero."""
    saida = {}
    for s in itens or []:
        chave = _POR_TIPO.get(s.get("type"))
        if not chave:
            continue
        v = numero(s.get("value"))
        if v is None and zerar_nulo and chave != "xg":
            v = 0
        if v is not None:
            saida[chave] = v
    return saida


def dois_lados(folha: list, home_id, away_id, campo: str, zerar_nulo: bool) -> tuple[dict, dict]:
    """(casa, fora) pelo id do time, como live._parse_stats; sem ids, pela ordem."""
    por_id, ordem = {}, []
    for t in folha or []:
        d = folha_por_chave(t.get(campo), zerar_nulo)
        ordem.append(d)
        tid = (t.get("team") or {}).get("id")
        if tid is not None:
            por_id[tid] = d
    if home_id in por_id and away_id in por_id:
        return por_id[home_id], por_id[away_id]
    if len(ordem) == 2:
        return ordem[0], ordem[1]
    return {}, {}


def segundo_tempo(cheia: dict, primeiro: dict) -> dict:
    return {k: cheia[k] - primeiro[k] for k in _SOMAM
            if k in cheia and k in primeiro and cheia[k] - primeiro[k] >= 0}


def linhas(casa: dict, fora: dict) -> list[dict]:
    """Na ordem de ITENS, so' o que os dois lados tem."""
    return [{"chave": chave, "rotulo": rotulo, "casa": casa[chave], "fora": fora[chave], "pct": pct}
            for _, chave, rotulo, pct in ITENS if chave in casa and chave in fora]


def periodos(cheia: tuple[dict, dict], primeiro: tuple[dict, dict] | None,
             tem_segundo: bool) -> dict:
    saida = {"jogo": linhas(*cheia)}
    if primeiro and primeiro[0] and primeiro[1]:
        saida["1t"] = linhas(*primeiro)
        if tem_segundo:
            saida["2t"] = linhas(segundo_tempo(cheia[0], primeiro[0]),
                                 segundo_tempo(cheia[1], primeiro[1]))
    return {k: v for k, v in saida.items() if v}


def da_folha(folha: list, home_id, away_id, status: str) -> dict:
    """Jogo rolando ou recem-acabado, pela folha da API (cache de live.py)."""
    zerar = bool(folha)
    cheia = dois_lados(folha, home_id, away_id, "statistics", zerar)
    # A folha do 1o tempo so' fecha no intervalo; antes disso ela e' o jogo.
    primeiro = (dois_lados(folha, home_id, away_id, "statistics_1h", zerar)
                if status not in ("1H",) else None)
    return periodos(cheia, primeiro, tem_segundo=status not in ("1H", "HT"))


def do_banco(linha: dict) -> dict:
    """Jogo encerrado, pelas colunas de `match_statistics`."""
    def lado(prefixo: str, colunas: dict) -> dict:
        d = {}
        for chave, col in colunas.items():
            v = numero(linha.get(f"{prefixo}_{col}"))
            if v is not None:
                d[chave] = v
        return d
    cheia = (lado("home", COLUNAS), lado("away", COLUNAS))
    primeiro = (lado("home", COLUNAS_1T), lado("away", COLUNAS_1T))
    return periodos(cheia, primeiro, tem_segundo=True)


def com_jogadores(per: dict, casa: dict, fora: dict) -> dict:
    """Junta no jogo inteiro o que vem da folha dos JOGADORES (desarme,
    duelo, drible, passe decisivo · estatisticas_de_jogadores.py). So' existe
    depois da coleta do jogo encerrado; o 1o e o 2o tempo nao tem."""
    import estatisticas_de_jogadores as ej
    if not per.get("jogo") or not casa or not fora:
        return per
    extra = [{"chave": chave, "rotulo": rotulo, "casa": casa[chave], "fora": fora[chave], "pct": False}
             for _, chave, rotulo in ej.ITENS if chave in casa and chave in fora]
    return {**per, "jogo": per["jogo"] + extra}


def sql_do_banco() -> str:
    cols = [f"{lado}_{c}" for c in list(COLUNAS.values()) + list(COLUNAS_1T.values())
            for lado in ("home", "away")]
    return ("SELECT status, home_goals, away_goals, home_team_id, away_team_id, " + ", ".join(cols)
            + " FROM match_statistics WHERE fixture_id = %s AND status IN ('FT','AET','PEN') LIMIT 1")
