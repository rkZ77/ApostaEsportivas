"""O recorte de rodadas do backfill (match_statistics_sync_service._ultimas_rodadas).

A TEMPORADA ANTERIOR SAIU DO MOTOR EM 18/10/2026 (decisao do usuario: o motor
le' todos os jogos da temporada atual da liga, e so' ela). Os testes do
condicional que completava o time curto com a temporada passada foram embora
com ele; a regra nova esta' em test_janela_de_historico_2026_08.py.
"""
from collectors.match_statistics_sync_service import _ultimas_rodadas


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
