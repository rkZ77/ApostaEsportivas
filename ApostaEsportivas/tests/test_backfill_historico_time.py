"""Backfill de historico por time (collectors/team_history_backfill_service.py).

O QUE ESTES TESTES PROTEGEM
---------------------------
Este coletor tem o mesmo FORMATO da coleta de amistosos da Copa que estourou a
cota da API em 2026-08-01 (ultimos 15 jogos de um time + uma folha de
estatistica por jogo). O que separa um do outro nao e' o formato, e' o gatilho
e o teto -- entao e' isso que precisa de teste: jogo que ja esta no banco nao
pode gastar requisicao, e o teto tem que cortar a rodada de verdade.

O resto cobre o que ja mordeu neste repositorio antes: lado trocado na folha de
estatistica e placar de prorrogacao entrando como placar dos 90 minutos.

Nenhum teste aqui toca banco nem API. O `requests` do modulo e substituido por
um duble, entao _api_get roda de verdade -- inclusive o contador de cota, que e
justamente o que nao pode ser simulado.
"""
import os

# O modulo levanta no import sem a chave (mesma regra do coletor original).
# Em teste o valor nunca sai daqui: nenhuma requisicao real acontece.
os.environ.setdefault("API_FOOTBALL_KEY", "chave-de-teste")

from collectors import team_history_backfill_service as backfill
from collectors.team_history_backfill_service import TeamHistoryBackfillService


# ── Dubles ────────────────────────────────────────────────────────────────
class _CursorFake:
    def __init__(self, retorno=None):
        self.execucoes = []
        self.retorno = retorno if retorno is not None else []
        self.rowcount = 1

    def execute(self, sql, params=None):
        self.execucoes.append((sql, params))

    def fetchall(self):
        return self.retorno

    def close(self):
        pass


class _ConnFake:
    def commit(self):
        pass

    def close(self):
        pass


class _RespostaFake:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return {"response": self._payload}


class _RequestsFake:
    """Substitui o modulo `requests` inteiro dentro do coletor."""

    def __init__(self, jogos=None, folha=None):
        self.jogos = jogos if jogos is not None else []
        self.folha = folha if folha is not None else []
        self.chamadas = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.chamadas.append(params)
        payload = self.jogos if "team" in (params or {}) else self.folha
        return _RespostaFake(payload)


def _servico(monkeypatch, jogos=None, folha=None, ja_no_banco=(), **kwargs):
    svc = TeamHistoryBackfillService(**kwargs)
    svc.cur = _CursorFake([(fid,) for fid in ja_no_banco])
    svc.conn = _ConnFake()
    svc.gravados = []
    svc.stats_sync._save_stats = lambda fx, h, a: svc.gravados.append((fx, h, a))
    svc.stats_sync._gravar_rodadas = lambda pares: None
    svc.http = _RequestsFake(jogos=jogos, folha=folha)
    monkeypatch.setattr(backfill, "requests", svc.http)
    return svc


def _jogo(fixture_id, status="FT", home_id=100, away_id=200,
          goals=(1, 0), fulltime=None, league_id=13, round_="Group Stage - 1"):
    return {
        "fixture": {"id": fixture_id, "date": "2026-08-01T22:00:00+00:00",
                    "status": {"short": status}, "referee": "Fulano"},
        "league": {"id": league_id, "name": "CONMEBOL Libertadores",
                   "country": "World", "season": 2026, "round": round_},
        "teams": {"home": {"id": home_id}, "away": {"id": away_id}},
        "goals": {"home": goals[0], "away": goals[1]},
        "score": {"halftime": {"home": 0, "away": 0},
                  "fulltime": {"home": (fulltime or goals)[0],
                               "away": (fulltime or goals)[1]}},
    }


def _folha(primeiro_id=100, escanteios_primeiro=7, segundo_id=200, escanteios_segundo=3):
    return [
        {"team": {"id": primeiro_id},
         "statistics": [{"type": "Corner Kicks", "value": escanteios_primeiro}]},
        {"team": {"id": segundo_id},
         "statistics": [{"type": "Corner Kicks", "value": escanteios_segundo}]},
    ]


_TIME = {"team_id": 100, "team_name": "Time", "jogos": 4}


# ── Cota: o que separa isto da coleta que estourou a API ──────────────────
def test_jogo_ja_completo_no_banco_nao_gasta_requisicao(monkeypatch):
    """A listagem custa 1. Com os 3 jogos ja no banco e a folha preenchida, o
    total para em 1 -- e' esse filtro que derruba o custo a quase zero da
    segunda rodada em diante."""
    svc = _servico(monkeypatch,
                   jogos=[_jogo(1), _jogo(2), _jogo(3)],
                   folha=_folha(), ja_no_banco=(1, 2, 3))

    svc._backfill_time(_TIME)

    assert svc.requisicoes == 1
    assert svc.gravados == []


def test_gasta_uma_requisicao_por_jogo_que_falta(monkeypatch):
    svc = _servico(monkeypatch,
                   jogos=[_jogo(1), _jogo(2), _jogo(3)],
                   folha=_folha(), ja_no_banco=(1,))

    svc._backfill_time(_TIME)

    # 1 listagem + 2 folhas (jogos 2 e 3); o jogo 1 ja estava completo
    assert svc.requisicoes == 3
    assert [fx["fixture_id"] for fx, _, _ in svc.gravados] == [2, 3]


def test_teto_corta_a_rodada_no_meio(monkeypatch):
    svc = _servico(monkeypatch,
                   jogos=[_jogo(i) for i in range(1, 11)],
                   folha=_folha(), teto_requisicoes=3)

    svc._backfill_time(_TIME)

    assert svc.requisicoes == 3, "o teto tem que parar a coleta, nao so' avisar"
    assert len(svc.gravados) == 2, "1 listagem + 2 folhas cabem em 3 requisicoes"


def test_teto_impede_ate_a_listagem_do_proximo_time(monkeypatch):
    """O corte vale entre times tambem: sem isso, cada time novo comecaria
    gastando a listagem dele mesmo com a cota ja no limite."""
    svc = _servico(monkeypatch, jogos=[], folha=_folha(), teto_requisicoes=1)
    svc.requisicoes = 1

    assert svc._cota_esgotada() is True


def test_jogo_nao_encerrado_nao_entra(monkeypatch):
    svc = _servico(monkeypatch,
                   jogos=[_jogo(1, status="NS"), _jogo(2, status="PST")],
                   folha=_folha())

    svc._backfill_time(_TIME)

    assert svc.gravados == []
    assert svc.requisicoes == 1, "so' a listagem; nenhuma folha foi pedida"


def test_prorrogacao_entra_na_coleta(monkeypatch):
    """AET/PEN sao gravados: e' mata-mata que este coletor existe pra cobrir."""
    svc = _servico(monkeypatch, jogos=[_jogo(1, status="AET")], folha=_folha())

    svc._backfill_time(_TIME)

    assert len(svc.gravados) == 1


# ── Conteudo da linha gravada ─────────────────────────────────────────────
def test_placar_de_prorrogacao_nao_vira_placar_dos_90(monkeypatch):
    """Caso real ja documentado no repositorio (Belgium x Senegal): goals 3x2
    com score.fulltime 2x2. Liquidar Over/Under pelo 3x2 e' liquidar um jogo
    que o apostador nao apostou."""
    svc = _servico(monkeypatch,
                   jogos=[_jogo(1, status="AET", goals=(3, 2), fulltime=(2, 2))],
                   folha=_folha())

    svc._backfill_time(_TIME)

    fx = svc.gravados[0][0]
    assert (fx["home_goals"], fx["away_goals"]) == (3, 2)
    assert (fx["home_goals_90"], fx["away_goals_90"]) == (2, 2)


def test_folha_fora_de_ordem_nao_troca_os_lados(monkeypatch):
    """A API nao garante que o mandante venha primeiro. Trocar os lados
    inverte escanteios/faltas/chutes de todo jogo coletado."""
    svc = _servico(monkeypatch,
                   jogos=[_jogo(1, home_id=100, away_id=200)],
                   # visitante primeiro: os 3 escanteios sao DELE
                   folha=_folha(primeiro_id=200, escanteios_primeiro=3,
                                segundo_id=100, escanteios_segundo=7))

    svc._backfill_time(_TIME)

    _, home_stats, away_stats = svc.gravados[0]
    assert home_stats[0]["value"] == 7
    assert away_stats[0]["value"] == 3


def test_folha_incompleta_nao_grava(monkeypatch):
    svc = _servico(monkeypatch, jogos=[_jogo(1)], folha=[])

    svc._backfill_time(_TIME)

    assert svc.gravados == []


def test_liga_e_temporada_vem_do_jogo_e_nao_da_fixture_de_hoje(monkeypatch):
    """O jogo pode ser de outra competicao e de outra temporada -- e' o ponto
    inteiro do coletor. Herdar a liga da partida de hoje gravaria um jogo do
    Paraguaio como se fosse da Libertadores."""
    svc = _servico(monkeypatch,
                   jogos=[_jogo(1, league_id=250)], folha=_folha())

    svc._backfill_time(_TIME)

    fx = svc.gravados[0][0]
    assert fx["league_id"] == 250
    assert fx["season"] == 2026


# ── Liga descoberta ───────────────────────────────────────────────────────
def test_liga_nova_entra_como_historico_e_nunca_desativa_liga_ativa(monkeypatch):
    svc = _servico(monkeypatch)
    svc._garantir_liga({"id": 250, "name": "Primera Division",
                        "country": "Paraguay", "season": 2026})

    sql, params = svc.cur.execucoes[-1]
    assert "INSERT INTO leagues" in sql
    assert "FALSE" in sql, "liga descoberta nao pode entrar como coletavel"
    assert "ON CONFLICT (league_id) DO NOTHING" in sql, \
        "sem isso, uma liga JA ativa seria rebaixada a historico por efeito colateral"
    assert params[0] == 250


def test_nome_da_liga_carrega_o_pais(monkeypatch):
    """'Primera Division' existe no Paraguai, no Chile e no Uruguai. Sem o
    pais viram tres linhas indistinguiveis nas telas."""
    svc = _servico(monkeypatch)
    svc._garantir_liga({"id": 250, "name": "Primera Division",
                        "country": "Paraguay", "season": 2026})

    assert svc.cur.execucoes[-1][1][1] == "Primera Division (Paraguay)"


def test_competicao_internacional_nao_ganha_sufixo_world(monkeypatch):
    svc = _servico(monkeypatch)
    svc._garantir_liga({"id": 13, "name": "CONMEBOL Libertadores",
                        "country": "World", "season": 2026})

    assert svc.cur.execucoes[-1][1][1] == "CONMEBOL Libertadores"


def test_liga_sem_id_nao_gera_escrita(monkeypatch):
    svc = _servico(monkeypatch)
    svc._garantir_liga({"name": "Sem id"})

    assert svc.cur.execucoes == []


# ── Gatilho ───────────────────────────────────────────────────────────────
def test_contagem_de_carencia_usa_o_mesmo_status_que_o_motor_le(monkeypatch):
    """MatchStatsService.get_last_n_all_competitions le so' status='FT'.
    Contar AET/PEN aqui faria um time aparecer com 8 jogos onde o motor
    enxerga 5, e o backfill nao dispararia em quem mais precisa -- mata-mata
    e' onde a prorrogacao acontece."""
    svc = _servico(monkeypatch)
    svc._times_carentes()

    sql, params = svc.cur.execucoes[-1]
    assert "ms.status = 'FT'" in sql
    assert params == (svc.min_jogos,)


def test_so_entra_time_que_joga_hoje(monkeypatch):
    svc = _servico(monkeypatch)
    svc._times_carentes()

    sql, _ = svc.cur.execucoes[-1]
    assert "FROM fixtures" in sql
    assert "status IN ('NS', 'TBD')" in sql


def test_time_de_pontos_corridos_nunca_entra(monkeypatch):
    """O motor le historico travado na liga numa fixture de pontos corridos
    (get_all_matches_full). Jogo de outra competicao coletado aqui nunca seria
    consultado: requisicao gasta em linha que ninguem le. E time de liga
    abaixo do minimo esta so' no comeco da temporada -- a propria liga resolve
    isso em algumas rodadas."""
    svc = _servico(monkeypatch)
    svc.cur.retorno = [(100, "Time do Brasileirao", 71, 3),
                       (101, "Time da Premier", 39, 2)]

    assert svc._times_carentes() == []


def test_time_de_copa_entra(monkeypatch):
    svc = _servico(monkeypatch)
    svc.cur.retorno = [(100, "Time da Libertadores", 13, 4),
                       (101, "Time da Sul-Americana", 11, 2),
                       (102, "Time da Champions", 2, 5)]

    assert [t["team_id"] for t in svc._times_carentes()] == [100, 101, 102]


def test_time_com_jogo_de_copa_e_de_liga_no_mesmo_dia_entra_uma_vez(monkeypatch):
    """Rodada remarcada pode dar dois jogos no mesmo dia. O historico e' do
    time, nao da partida: basta um deles ser de copa, e a coleta acontece uma
    vez so'."""
    svc = _servico(monkeypatch)
    svc.cur.retorno = [(100, "Time", 71, 4), (100, "Time", 13, 4)]

    carentes = svc._times_carentes()
    assert len(carentes) == 1
    assert carentes[0]["team_id"] == 100


def test_gatilho_da_coleta_e_o_mesmo_predicado_da_leitura(monkeypatch):
    """Coleta e leitura tem que andar juntas. Se um dia uma competicao entrar
    ou sair do CLUB_CUP, este teste garante que o coletor acompanha em vez de
    manter a propria lista de ligas."""
    from services.pick_engine import competition_profile as cp

    svc = _servico(monkeypatch)
    svc.cur.retorno = [(idx, f"Time {lid}", lid, 3)
                       for idx, lid in enumerate((13, 11, 73, 2, 3, 848, 71, 72, 39, 140))]

    entraram = {t["league_id"] for t in svc._times_carentes()}
    esperado = {lid for lid in (13, 11, 73, 2, 3, 848, 71, 72, 39, 140)
                if cp.uses_all_competitions_history(lid)}
    assert entraram == esperado


def test_limite_pedido_a_api_e_o_mesmo_que_o_motor_le():
    """Pedir mais que o motor le e' requisicao gasta em linha que ninguem
    consulta; pedir menos deixa o motor com fome.

    A versao anterior deste teste comparava a fonte contra a string "limit=15",
    e cumpriu o papel: acusou no dia em que o LIMIT do motor subiu pra 30. A
    correcao boa nao era atualizar o numero nos dois lugares, era APAGAR um dos
    dois -- o coletor agora importa a constante do motor, e este teste so'
    garante que ninguem volte a copiar.
    """
    from services import match_stats_service

    assert backfill.ULTIMOS_PADRAO is match_stats_service.DEFAULT_LIMIT_MULTI


def test_teto_de_requisicoes_cobre_pelo_menos_um_time_inteiro():
    """Teto menor que (1 listagem + ULTIMOS_PADRAO folhas) faria toda rodada
    parar no meio do primeiro time, sem nunca completar ninguem."""
    assert backfill.TETO_REQUISICOES_PADRAO >= backfill.ULTIMOS_PADRAO + 1


def test_minimo_do_backfill_fica_acima_do_minimo_duro_do_motor():
    """validate_history reprova abaixo de 5. Mirar em 5 deixaria o time em
    cima da linha, e pool_and_field ainda corta o historico pelo mando."""
    assert backfill.MIN_JOGOS_PADRAO > 5
