"""A temporada anterior entra no histórico só quando a corrente não basta.

O motor lia `AND ms.season = %s` e ponto. Em começo de temporada isso é um teto
que nenhum limiar contorna: as seis ligas europeias que reiniciaram em agosto
tinham 6 ou 7 jogos por time na semana de 14/09/2026, e delas saiu o bloco de
amostra curta que mediu 53,7% e -11,57u. A nota está no topo de
pick_engine/config.py e em get_all_matches_full.

O que estes testes travam é o CONDICIONAL. Alargar sempre mudaria a taxa de todo
pick do Brasileirão (28ª rodada) por um motivo que ninguém mediu; alargar nunca
deixa a liga que reiniciou muda por três rodadas. A regra só pode valer pra quem
está curto.
"""
from collectors.match_statistics_sync_service import _ultimas_rodadas
from services.match_stats_service import (
    LIMIAR_TEMPORADA_ANTERIOR,
    _somente_temporada_corrente_se_bastar,
)
from services.pick_engine.config import AMOSTRA_RICA


def jogos(quantos: int, season: int) -> list:
    return [{"season": season, "fixture_id": i} for i in range(quantos)]


def test_limiar_e_o_dobro_do_piso_de_amostra():
    """`pool_and_field` corta o pool pelo mando, então 8 no pool pede ~16 no
    histórico. O número sai do config do motor, não escrito à mão aqui."""
    assert LIMIAR_TEMPORADA_ANTERIOR == AMOSTRA_RICA * 2


def test_temporada_cheia_descarta_a_anterior():
    """Brasileirão na 28ª rodada continua lendo só a temporada dele."""
    historico = jogos(28, 2026) + jogos(38, 2025)

    resultado = _somente_temporada_corrente_se_bastar(historico, 2026)

    assert len(resultado) == 28
    assert all(j["season"] == 2026 for j in resultado)


def test_temporada_curta_mantem_a_anterior():
    """La Liga na 6ª rodada: é exatamente o caso que estava quebrado."""
    historico = jogos(6, 2026) + jogos(30, 2025)

    resultado = _somente_temporada_corrente_se_bastar(historico, 2026)

    assert len(resultado) == 36


def test_o_limiar_e_inclusivo_no_ponto_de_corte():
    """Com 16 na corrente a anterior já não entra: 16 é o que basta, não o que
    falta."""
    no_ponto = _somente_temporada_corrente_se_bastar(
        jogos(LIMIAR_TEMPORADA_ANTERIOR, 2026) + jogos(10, 2025), 2026)
    um_a_menos = _somente_temporada_corrente_se_bastar(
        jogos(LIMIAR_TEMPORADA_ANTERIOR - 1, 2026) + jogos(10, 2025), 2026)

    assert len(no_ponto) == LIMIAR_TEMPORADA_ANTERIOR
    assert len(um_a_menos) == LIMIAR_TEMPORADA_ANTERIOR - 1 + 10


def test_time_sem_temporada_anterior_no_banco_nao_quebra():
    """Time promovido: a temporada passada dele está sob outro league_id, então
    a consulta volta só com a corrente. Não é erro, é o resultado certo."""
    resultado = _somente_temporada_corrente_se_bastar(jogos(5, 2026), 2026)

    assert len(resultado) == 5


# ── O recorte de rodadas, que é o freio de cota do backfill ───────────────
def fx(rodada, data):
    return {"league": {"round": rodada}, "fixture": {"date": data, "id": data}}


def test_pega_so_as_rodadas_mais_recentes():
    resposta = [
        fx("Regular Season - 1", "2025-08-10T16:00:00+00:00"),
        fx("Regular Season - 2", "2025-08-17T16:00:00+00:00"),
        fx("Regular Season - 3", "2025-08-24T16:00:00+00:00"),
    ]

    escolhidos = _ultimas_rodadas(resposta, 2)

    assert {f["league"]["round"] for f in escolhidos} == {
        "Regular Season - 2", "Regular Season - 3"}


def test_rodada_e_ordenada_pela_data_e_nao_pelo_rotulo():
    """"Group Stage - 2" e "Regular Season - 12" não são comparáveis como
    texto, e o número no rótulo muda de formato entre competições."""
    resposta = [
        fx("Group Stage - 2", "2025-09-01T16:00:00+00:00"),
        fx("Regular Season - 12", "2025-05-01T16:00:00+00:00"),
    ]

    escolhidos = _ultimas_rodadas(resposta, 1)

    assert escolhidos[0]["league"]["round"] == "Group Stage - 2"


def test_jogo_sem_rodada_fica_fora_do_recorte():
    """Sem rodada não há como dizer se o jogo é recente · e ausência de dado
    nunca vira inclusão por padrão."""
    resposta = [fx(None, "2025-09-01T16:00:00+00:00"),
                fx("Regular Season - 3", "2025-08-24T16:00:00+00:00")]

    escolhidos = _ultimas_rodadas(resposta, 5)

    assert len(escolhidos) == 1
    assert escolhidos[0]["league"]["round"] == "Regular Season - 3"


# ── `apenas_liga` tem de estreitar o LAÇO, não só a consulta de times ─────
def test_apenas_liga_estreita_o_laco_de_ligas(monkeypatch):
    """Bug pré-existente que a flag do backfill tornou visível (24/09): o
    recorte valia só pra `teams`, e o laço seguia varrendo todas as ligas
    cadastradas -- uma listagem cada, e a `temporada` pedida aplicada a todas.
    Ficou invisível enquanto o filtro exigia os dois times; com
    `exigir_os_dois_times=False`, o backfill de uma liga passou a gravar a
    temporada passada de outras."""
    from collectors import match_statistics_sync_service as mod

    consultadas = []

    def falso_buscar(url, params, origem=None, **kw):
        consultadas.append(params["league"])
        return []

    monkeypatch.setattr(mod, "load_leagues_from_db",
                        lambda: [{"league_id": 140, "season": 2026},
                                 {"league_id": 2, "season": 2026}])
    monkeypatch.setattr(mod, "buscar", falso_buscar)

    servico = mod.MatchStatisticsSyncService()

    class CursorFalso:
        description = None

        def execute(self, *a, **kw):
            pass

        def fetchall(self):
            return []

    servico.cur = CursorFalso()
    servico._gravar_rodadas = lambda pares: None
    servico._load_fixtures(use_date_filter=False, apenas_liga=140,
                           temporada=2025, exigir_os_dois_times=False)

    assert consultadas == [140]
