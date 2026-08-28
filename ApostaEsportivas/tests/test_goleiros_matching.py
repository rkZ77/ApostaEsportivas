"""Parsing da oferta e resolucao do jogador no motor de props.

Os dois pontos onde uma oferta real morre em silencio: a notacao do value_name
(as casas escrevem o mesmo produto de formas diferentes) e o casamento de nome
com `player_match_stats`. Casos tirados de dados reais de 2026-08-05, quando
isto era o goleiros_pipeline.

MUDOU DE ENDERECO EM 2026-08-28, e nao de exigencia. O goleiros_pipeline foi
apagado; as duas funcoes que estes casos exercitam ja tinham sido promovidas a
`services/player_stats_engine/name_match.py`, que e' o que o motor de hoje
chama pra TODO metodo (defesas, chutes, faltas...) -- entao os mesmos casos
agora protegem seis mercados em vez de um.
"""
from services.player_stats_engine import config as ps_cfg
from services.player_stats_engine.name_match import (
    parse_valor as _parse_valor,
    resolver as _resolver_goleiro,
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
# Um pick por jogador (2026-08-07, reescrito em 2026-08-28)
# --------------------------------------------------------------------------
#
# A REGRA SOBREVIVEU AO PIPELINE QUE A INVENTOU, e a diferenca importa.
#
# O `melhor_por_goleiro` do goleiros_pipeline reduzia em DOIS passos: entre
# casas na mesma linha decidia pelo maior PRECO (porque o score premia odd
# baixa, e comparar duas casas pelo score escolheria o pior preco pra
# exatamente a mesma aposta), e entre linhas diferentes decidia pelo SCORE.
#
# O Player Stats, que herdou o mercado em 27/08, aplica um passo so': ordena
# tudo por `pick_score` e fica com o primeiro de cada jogador. Duas casas na
# mesma linha voltam a ser comparadas por score.
#
# Isto esta escrito aqui porque e' uma perda real e conhecida, nao um detalhe
# esquecido: quem for reintroduzir o desempate por preco vai achar a
# justificativa neste comentario em vez de redescobri-la num pick ruim.


def test_um_pick_por_jogador_continua_ligado():
    """Duas linhas do mesmo jogador sao a mesma aposta em graus diferentes:
    publicar as duas dobra a exposicao ao mesmo erro."""
    assert ps_cfg.UM_PICK_POR_JOGADOR is True


def test_a_reducao_fica_com_a_de_maior_score():
    """Trava o criterio no codigo que roda hoje. A ordenacao e' por
    `pick_score` DESC e o primeiro de cada `player_id` e' o que sai."""
    import inspect
    from engine_pipelines import player_stats_pipeline

    fonte = inspect.getsource(player_stats_pipeline.run_player_stats_engine)
    assert 'aprovados.sort(key=lambda par: par[0]["pick_score"], reverse=True)' in fonte
    assert 'chave = c["jogador"]["player_id"]' in fonte
    assert "cfg.UM_PICK_POR_JOGADOR and chave in vistos" in fonte
