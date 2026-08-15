"""
Banca de demonstração usada nas cenas de /banca e /meus-picks.

Por que fixture e não conta de verdade: noprod aponta pro banco de PRODUÇÃO.
Uma conta demo que "seguiu todos os picks da IA" entraria no ranking real --
`GET /api/leaderboard` monta a tabela a partir de `user_followed_picks` sem
nenhum filtro de conta de teste, e basta 3 picks resolvidos pra aparecer. Então
a banca do vídeo é servida por `page.route`, sem escrever uma linha no banco.

O payload é montado com a mesma aritmética de `_compute_follow_pnl` em
`routers/banca.py`, então tudo que aparece na tela fecha: o gráfico, o ROI, o
yield e o saldo final batem com a lista de apostas.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

BANCA_INICIAL = 500.0
VALOR_UNIDADE = 25.0  # 5% da banca, dentro da faixa que a tela chama de saudável

# (dias_atras, casa, fora, mercado, linha, odd, unidades, resultado)
# resultado None = ainda pendente, aparece na aba de abertas.
#
# Calibragem importante: os números aqui vão pra um vídeo de captação, então
# têm que ser um mês bom porém defensável, não fantasia. A primeira versão
# desta semente dava 65% de ROI em três semanas · descartada. O alvo é ROI na
# casa de 13%, yield ~7% e acerto ~61%, com stake variando por confiança.
#
_SEMENTE = [
    (19, "Palmeiras",      "Fortaleza",     "Over/Under Gols",   "Over 2.5",   1.82, 2.0, "GREEN"),
    (19, "Bayern München", "Werder Bremen", "Resultado Final",   "Casa",       1.55, 2.0, "GREEN"),
    (17, "Internacional",  "Vasco",         "Ambas Marcam",      "Sim",        1.90, 3.0, "RED"),
    (16, "Arsenal",        "Everton",       "Escanteios",        "Over 9.5",   1.74, 2.0, "GREEN"),
    (15, "Flamengo",       "Bragantino",    "Over/Under Gols",   "Over 2.5",   1.68, 2.0, "GREEN"),
    (14, "Real Madrid",    "Getafe",        "Handicap Asiático", "-1.0",       1.88, 2.0, "PUSH"),
    (13, "Grêmio",         "Criciúma",      "Resultado Final",   "Casa",       1.72, 3.0, "RED"),
    (12, "Inter",          "Lecce",         "Over/Under Gols",   "Under 3.5",  1.61, 2.0, "GREEN"),
    (11, "Porto",          "Braga",         "Ambas Marcam",      "Sim",        1.79, 1.0, "RED"),
    (10, "Atlético-MG",    "Cuiabá",        "Faltas",            "Over 22.5",  1.85, 1.0, "GREEN"),
    (9,  "Liverpool",      "Brighton",      "Over/Under Gols",   "Over 2.5",   1.66, 2.0, "GREEN"),
    (8,  "Botafogo",       "Juventude",     "Escanteios",        "Over 8.5",   1.70, 2.0, "RED"),
    (7,  "Barcelona",      "Osasuna",       "Resultado Final",   "Casa",       1.44, 2.0, "GREEN"),
    (6,  "São Paulo",      "Athletico-PR",  "Over/Under Gols",   "Under 2.5",  1.75, 2.0, "GREEN"),
    (5,  "Milan",          "Torino",        "Ambas Marcam",      "Não",        1.92, 1.0, "RED"),
    (4,  "Bahia",          "Vitória",       "Escanteios",        "Over 9.5",   1.80, 2.0, "RED"),
    (3,  "PSG",            "Nantes",        "Handicap Asiático", "-1.5",       1.86, 2.0, "GREEN"),
    (2,  "Cruzeiro",       "Fluminense",    "Over/Under Gols",   "Over 2.5",   1.77, 2.0, "GREEN"),
    (0,  "Chelsea",        "Aston Villa",   "Over/Under Gols",   "Over 2.5",   1.73, 2.0, None),
    (0,  "Corinthians",    "Santos",        "Ambas Marcam",      "Sim",        1.84, 2.0, None),
]


def _lucro_unitario(resultado: str, odd: float) -> float:
    """Mesma tabela de `_compute_follow_pnl`, em lucro por unidade apostada."""
    if resultado == "GREEN":
        return odd - 1
    if resultado == "RED":
        return -1.0
    if resultado == "PUSH":
        return 0.0
    if resultado == "HALF-WIN":
        return (odd - 1) / 2
    return -0.5  # HALF-LOSS


def _sequencia(resolvidos: list[dict]) -> dict:
    """Sequência atual (do mais recente pra trás) e a melhor do período."""
    ordem = sorted(resolvidos, key=lambda e: e["followed_at"], reverse=True)
    atual, tipo = 0, None
    for e in ordem:
        if e["result"] not in ("GREEN", "RED"):
            continue
        t = "green" if e["result"] == "GREEN" else "red"
        if tipo is None:
            tipo, atual = t, 1
        elif tipo == t:
            atual += 1
        else:
            break

    melhor, corrida = 0, 0
    for e in sorted(resolvidos, key=lambda e: e["followed_at"]):
        if e["result"] == "GREEN":
            corrida += 1
            melhor = max(melhor, corrida)
        elif e["result"] == "RED":
            corrida = 0
    return {"streak": atual, "streak_type": tipo, "best_streak": melhor}


def banca(hoje: date | None = None) -> dict:
    """Payload completo de `GET /api/banca`, com todos os derivados coerentes."""
    hoje = hoje or date.today()

    entradas: list[dict] = []
    saldo = BANCA_INICIAL
    for i, (atras, casa, fora, mercado, linha, odd, unidades, resultado) in enumerate(_SEMENTE):
        quando = datetime.combine(hoje - timedelta(days=atras), datetime.min.time())
        quando += timedelta(hours=15, minutes=20 + (i * 7) % 40)

        if resultado:
            lucro_u = _lucro_unitario(resultado, odd)
            pnl = lucro_u * unidades * VALOR_UNIDADE
            saldo += pnl
        else:
            lucro_u = pnl = None

        entradas.append({
            "id": 9000 + i,
            "pick_id": 7000 + i,
            "pick_type": "vip" if i % 3 else "free",
            "stake_units": unidades,
            "followed_at": quando.isoformat(),
            "home_team_name": casa,
            "away_team_name": fora,
            "home_team_id": None,
            "away_team_id": None,
            "market": mercado,
            "line": linha,
            "odd": odd,
            "actual_odd": None,
            "result": resultado,
            "profit_units": lucro_u,
            "pnl": round(pnl, 2) if pnl is not None else None,
            "bankroll_after": round(saldo, 2) if pnl is not None else None,
        })

    resolvidos = [e for e in entradas if e["result"]]
    greens = sum(1 for e in resolvidos if e["result"] == "GREEN")
    reds = sum(1 for e in resolvidos if e["result"] == "RED")
    push = sum(1 for e in resolvidos if e["result"] == "PUSH")
    pnl_total = sum(e["pnl"] for e in resolvidos)

    unidades_lucro = sum(e["pnl"] / VALOR_UNIDADE for e in resolvidos)
    unidades_apostadas = sum(e["stake_units"] for e in resolvidos)

    grafico = [
        {"date": e["followed_at"][:10], "bankroll": e["bankroll_after"]}
        for e in entradas if e["pnl"] is not None
    ]

    melhor = max(resolvidos, key=lambda e: e["pnl"])
    pior = min(resolvidos, key=lambda e: e["pnl"])
    seq = _sequencia(resolvidos)

    return {
        "bankroll_start": BANCA_INICIAL,
        "bankroll_current": round(saldo, 2),
        "unit_value": VALOR_UNIDADE,
        # False: a tela some com o botão "Configurar banca" quando o mês já foi
        # configurado, que é o estado certo pras cenas de acompanhamento.
        "can_configure": False,
        "total_followed": len(entradas),
        "total_resolved": len(resolvidos),
        "greens": greens,
        "reds": reds,
        "push": push,
        "half_wins": 0,
        "half_loss": 0,
        "win_rate": round(greens / len(resolvidos) * 100),
        "roi": round(pnl_total / BANCA_INICIAL * 100, 1),
        "yield_roi": round(unidades_lucro / unidades_apostadas * 100, 1),
        "ia_roi": 8.4,
        "total_pnl": round(pnl_total, 2),
        "streak": seq["streak"],
        "streak_type": seq["streak_type"],
        "best_streak": seq["best_streak"],
        "best_pick": melhor,
        "worst_pick": pior,
        "entries": entradas,
        "resolved_total": len(resolvidos),
        "has_more_resolved": False,
        "chart": grafico,
    }


def banca_zerada() -> dict:
    """Estado 'ainda não configurei', usado na cena de configurar a banca."""
    vazia = banca()
    vazia.update({
        "bankroll_start": 100.0, "bankroll_current": 100.0, "unit_value": 1.0,
        "can_configure": True, "total_followed": 0, "total_resolved": 0,
        "greens": 0, "reds": 0, "push": 0, "win_rate": 0, "roi": 0,
        "yield_roi": 0, "total_pnl": 0, "streak": 0, "streak_type": None,
        "best_streak": 0, "best_pick": None, "worst_pick": None,
        "entries": [], "resolved_total": 0, "chart": [],
    })
    return vazia


if __name__ == "__main__":
    d = banca()
    print(f"banca inicial : R$ {d['bankroll_start']:.2f}")
    print(f"banca atual   : R$ {d['bankroll_current']:.2f}")
    print(f"lucro         : R$ {d['total_pnl']:.2f}")
    print(f"ROI           : {d['roi']}%")
    print(f"yield         : {d['yield_roi']}%")
    print(f"win rate      : {d['win_rate']}%  ({d['greens']}G / {d['reds']}R / {d['push']}P)")
    print(f"sequencia     : {d['streak']} {d['streak_type']} (melhor: {d['best_streak']})")
    print(f"entradas      : {d['total_followed']} ({d['total_resolved']} resolvidas)")
