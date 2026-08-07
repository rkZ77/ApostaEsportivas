"""Parsing da oferta e resolucao do goleiro no pipeline de defesas.

Os dois pontos onde uma oferta real morre em silencio: a notacao do value_name
(as casas escrevem o mesmo produto de formas diferentes) e o casamento de nome
com `player_match_stats`. Casos tirados de dados reais de 2026-08-05.
"""
from engine_pipelines.goleiros_pipeline import (
    _parse_valor, _resolver_goleiro, melhor_por_goleiro,
)

PALMEIRAS, FORTALEZA, GREMIO = 121, 154, 130


def _gk(nome_norm, team_id, player_id):
    return {
        "player_id": player_id, "player_name": nome_norm.title(),
        "team_id": team_id, "team_name": f"time-{team_id}",
        "saves_avg": 2.5, "jogos": 10, "nome_norm": nome_norm,
    }


# ── value_name ────────────────────────────────────────────────────────────
def test_formato_da_betano_sem_sinal():
    assert _parse_valor("Weverton Pereira - 2") == ("Weverton Pereira", 2)


def test_formato_da_bet365_com_mais():
    """'3+' e '3' sao o MESMO produto (N ou mais defesas) -- a regex antiga
    exigia digito no fim e descartava toda a oferta da Bet365."""
    assert _parse_valor("Joao Ricardo - 3+") == ("Joao Ricardo", 3)


def test_formato_desconhecido_nao_vira_chute():
    assert _parse_valor("Joao Ricardo") is None
    assert _parse_valor("Joao Ricardo - ") is None
    assert _parse_valor("") is None


# ── resolucao do goleiro ──────────────────────────────────────────────────
def test_nome_exato():
    base = [_gk("carlos miguel", PALMEIRAS, 1)]

    assert _resolver_goleiro("Carlos Miguel", base, FORTALEZA, PALMEIRAS)["player_id"] == 1


def test_nome_longo_da_casa_casa_com_nome_curto_da_api():
    """Betano publica 'Weverton Pereira', a API grava 'Weverton'."""
    base = [_gk("weverton", PALMEIRAS, 1)]

    assert _resolver_goleiro("Weverton Pereira", base, FORTALEZA, PALMEIRAS)["player_id"] == 1


def test_homonimo_de_outro_time_nao_e_usado():
    """O caso que motivou o fix: existe um 'Weverton' no Gremio, que nem esta
    neste jogo. Casar por nome pegaria o adversario errado e inverteria a
    previsao -- pior que nao gerar pick."""
    base = [_gk("weverton", GREMIO, 99)]

    assert _resolver_goleiro("Weverton Pereira", base, FORTALEZA, PALMEIRAS) is None


def test_nome_exato_ganha_de_parcial_do_outro_time():
    """A casa escreveu exatamente o nome que a API tem pro goleiro do
    Palmeiras -- isso e' sinal forte e vence o parcial do adversario."""
    base = [_gk("weverton", PALMEIRAS, 1), _gk("weverton silva", FORTALEZA, 2)]

    assert _resolver_goleiro("Weverton", base, FORTALEZA, PALMEIRAS)["player_id"] == 1


def test_dois_parciais_no_mesmo_jogo_devolvem_none():
    """Sem nome exato, dois goleiros do jogo compativeis com a oferta e'
    ambiguidade real: descarta em vez de escolher um dos dois no chute."""
    base = [_gk("weverton", PALMEIRAS, 1), _gk("weverton", FORTALEZA, 2)]

    assert _resolver_goleiro("Weverton Pereira", base, FORTALEZA, PALMEIRAS) is None


def test_acento_nao_atrapalha():
    base = [_gk("joao ricardo", FORTALEZA, 1)]

    assert _resolver_goleiro("João Ricardo", base, FORTALEZA, PALMEIRAS)["player_id"] == 1


# --------------------------------------------------------------------------
# Deduplicacao por goleiro (2026-08-07)
# --------------------------------------------------------------------------
def _cand(player_id, n_defesas, odd, edge):
    return {
        "goleiro": {"player_id": player_id, "player_name": f"gk-{player_id}"},
        "n_defesas": n_defesas, "odd": odd, "edge": edge,
    }


def test_linhas_do_mesmo_goleiro_viram_um_pick_so():
    """Regressao 2026-08-07: assim que o teto de odd 2.00 saiu, os jogos do dia
    devolveram QUATRO candidatos do mesmo goleiro (4+ @ 3.75, 5+ @ 7.00, 5+ @
    5.70 de outra casa e 6+ @ 10.50). Sao a mesma aposta em graus diferentes --
    6+ implica 5+ implica 4+ -- e publicar os quatro multiplicaria por quatro a
    exposicao do assinante num goleiro so'."""
    vagner = 900
    candidatos = [
        _cand(vagner, 4, 3.75, 0.1005),
        _cand(vagner, 5, 7.00, 0.1025),
        _cand(vagner, 5, 5.70, 0.0699),
        _cand(vagner, 6, 10.50, 0.0632),
    ]

    reduzidos = melhor_por_goleiro(candidatos)

    assert len(reduzidos) == 1
    assert reduzidos[0]["odd"] == 7.00
    assert reduzidos[0]["n_defesas"] == 5


def test_mesma_linha_em_duas_casas_fica_com_a_odd_maior():
    """Este pipeline le odd RAW, entao nao tem o 'melhor preco por linha' que o
    de faltas faz. Maior edge resolve: na mesma linha, odd maior tem edge
    maior."""
    reduzidos = melhor_por_goleiro([
        _cand(900, 5, 5.70, 0.0699),
        _cand(900, 5, 7.00, 0.1025),
    ])

    assert len(reduzidos) == 1
    assert reduzidos[0]["odd"] == 7.00


def test_goleiros_diferentes_continuam_sendo_dois_picks():
    """A reducao e' por goleiro, nao por jogo: os dois goleiros da partida sao
    apostas distintas e ambos podem sair."""
    reduzidos = melhor_por_goleiro([_cand(900, 5, 7.00, 0.10), _cand(901, 3, 2.50, 0.08)])

    assert len(reduzidos) == 2
