"""A "Entenda esta análise" diz DE ONDE vieram os jogos da taxa.

O texto que o assinante lê sempre disse "Taxa real ponderada de 75.7% em 32
jogos" e nunca disse a origem. Enquanto todo pick vinha de pontos corridos,
"32 jogos" queria dizer "32 jogos daquela liga" e a omissão não mentia.

Depois de 2026-08-13, copa lê o histórico de TODAS as competições do time: os
mesmos "32 jogos" podem misturar Brasileirão, Libertadores e Copa do Brasil, e
o assinante seguia lendo a taxa como se fosse da competição do jogo. Foi o
usuário quem apontou a lacuna, olhando um pick real em produção.

Aqui trava-se que o número sai MEDIDO da amostra que gerou a taxa, e que pick
de liga não ganha ruído nenhum.
"""
from datetime import date

from services.pick_engine import stats_model
from services.pick_engine.explanation import build_explanation


def jogo(league_id, rank=None, total_corners=12):
    return {"match_date": "2026-08-10", "league_id": league_id, "status": "FT",
            "home_team_id": 1, "away_team_id": 2, "opponent_rank": rank,
            "total_corners": total_corners, "home_corners": 6, "away_corners": 6}


def taxa_de(historico):
    return stats_model.weighted_rate(
        historico, lambda m: 1 if m["total_corners"] > 9 else 0,
        reference_date=date(2026, 8, 12))


def candidato(taxa, **extra):
    base = {
        "market_name": "Escanteios Mais/Menos", "value_label": "Over 9.5",
        "odd": 1.80, "taxa_real": taxa["taxa_ponderada"], "ev": 0.2, "edge": 0.1,
        "amostra": taxa["amostra"], "amostra_label": taxa["amostra_label"],
        "composicao": taxa["composicao"], "confidence": 0.8, "risco": "BAIXO",
        "final_score": 1.0, "stake_units": 2, "bookmakers_count": 2,
    }
    base.update(extra)
    return base


def texto(historico, **extra):
    exp = build_explanation(candidato(taxa_de(historico), **extra))
    return " | ".join(exp["positive_factors"] + exp["negative_factors"] + exp["risks"])


# ── A composição sai medida ───────────────────────────────────────────────
def test_amostra_de_copa_diz_que_reune_varias_competicoes():
    hist = [jogo(71) for _ in range(8)] + [jogo(13) for _ in range(4)] + [jogo(73) for _ in range(2)]

    assert "reúne 3 competições" in texto(hist)


def test_diz_quantos_jogos_vieram_da_competicao_mais_frequente():
    """"3 competições" sozinho não diz se a mistura é 10/1/1 ou 4/4/4."""
    hist = [jogo(71) for _ in range(8)] + [jogo(13) for _ in range(4)] + [jogo(73) for _ in range(2)]

    assert "8 jogos da mais frequente" in texto(hist)


def test_pick_de_liga_nao_ganha_a_frase():
    """Histórico de uma competição só é o caso comum. Anunciar "1 competição"
    em todo pick de Brasileirão seria ruído sem informação."""
    hist = [jogo(71) for _ in range(10)]

    assert "competições" not in texto(hist)


# ── Adversário desconhecido vira risco declarado ──────────────────────────
def test_adversario_desconhecido_aparece_como_risco():
    """É o que diz ao assinante que a ponderação por força rodou cega naqueles
    jogos · costuma acontecer com adversário de campeonato estrangeiro que o
    site não coleta, justamente em copa."""
    hist = [jogo(13, rank=3) for _ in range(4)] + [jogo(13, rank=None) for _ in range(6)]

    t = texto(hist)
    assert "Em 6 dos 10 jogos" in t
    assert "classificação do adversário" in t


def test_amostra_toda_conhecida_nao_gera_risco():
    hist = [jogo(71, rank=5) for _ in range(10)]

    assert "classificação do adversário" not in texto(hist)


# ── O número é medido, não estimado ───────────────────────────────────────
def test_composicao_conta_so_os_jogos_que_entraram_na_taxa():
    """A composição sai de `counted` (jogos que a taxa usou), não da lista
    bruta · o módulo de explicação não inventa número, e este não pode ser o
    primeiro."""
    hist = [jogo(71) for _ in range(5)] + [jogo(13) for _ in range(5)]
    taxa = taxa_de(hist)

    assert taxa["composicao"]["total"] == taxa["amostra"]
    assert sum(taxa["composicao"]["competicoes"].values()) == taxa["amostra"]


def test_prorrogacao_descartada_nao_conta_na_composicao():
    """Coerência com o pool: jogo que saiu por não caber em 90 minutos não pode
    aparecer na contagem de origem."""
    hist = [jogo(13) for _ in range(4)]
    pool, _ = stats_model.pool_and_field(
        "corners", "total", hist + [dict(jogo(13), status="AET")], [],
        home_team_id=1, away_team_id=2)

    assert taxa_de(pool)["composicao"]["total"] == 4
