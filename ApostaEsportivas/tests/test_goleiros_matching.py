"""Parsing da oferta e resolucao do goleiro no pipeline de defesas.

Os dois pontos onde uma oferta real morre em silencio: a notacao do value_name
(as casas escrevem o mesmo produto de formas diferentes) e o casamento de nome
com `player_match_stats`. Casos tirados de dados reais de 2026-08-05.
"""
from engine_pipelines.goleiros_pipeline import _parse_valor, _resolver_goleiro

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
