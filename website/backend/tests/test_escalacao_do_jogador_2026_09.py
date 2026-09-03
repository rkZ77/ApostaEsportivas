"""A escalação decide se o pick de jogador tem chance (2026-09-02).

Pick de jogador é sobre uma pessoa, e até 02/09 ninguém perguntava se ela ia
entrar em campo: titular poupado virava um pick que só podia dar RED, e o card
seguia anunciando a aposta até o apito.

`lineups_sweep.py` lê `/fixtures/lineups` perto do jogo e faz três coisas, e
são elas que este arquivo trava:

  1. NÃO ANULAR SEM ESCALAÇÃO. Resposta vazia, ou com formação e lista de
     titulares vazia (o provedor devolve isso enquanto o clube não confirma),
     não pode virar "ninguém foi escalado" -- isso anularia todos os picks da
     partida de uma vez.
  2. ANULAR SÓ QUEM NEM FOI RELACIONADO, e como PUSH. Quem começa no BANCO
     não é anulado: aposta de estatística individual vale se o jogador entrar
     em campo, e quem entra aos 60' e dá dois chutes bateu uma linha de dois
     chutes. Anular ali tiraria do apostador uma aposta que a casa dele pagou.
     (A primeira versão anulava todo mundo fora do XI inicial · corrigido em
     02/09, antes de ir pra produção.)
  3. NÃO REESCREVER RESULTADO. O UPDATE tem `result IS NULL`, senão uma
     passada tardia transformaria um GREEN já liquidado em anulação.

Nada aqui toca banco: é parsing puro e leitura do SQL.
"""
import os
import re
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)

import lineups_sweep as ls


# ── 1. o que conta como escalação publicada ─────────────────────────────────
def test_soma_os_dois_times():
    times = [
        {"startXI": [{"player": {"id": 1}}, {"player": {"id": 2}}],
         "substitutes": [{"player": {"id": 3}}]},
        {"startXI": [{"player": {"id": 10}}],
         "substitutes": [{"player": {"id": 11}}, {"player": {"id": 12}}]},
    ]
    titulares, reservas = ls._ids_da_escalacao(times)
    assert titulares == [1, 2, 10]
    assert reservas == [3, 11, 12]


def test_jogador_sem_id_e_descartado():
    """Sem id não dá pra casar com o pick, e casar por nome é o tipo de
    aproximação que já falhou por acento neste projeto."""
    times = [{"startXI": [{"player": {"id": None, "name": "Fulano"}},
                          {"player": {"id": 7}}]}]
    titulares, _ = ls._ids_da_escalacao(times)
    assert titulares == [7]


@pytest.mark.parametrize("resposta", [
    [],                                                   # ainda não saiu
    [{"formation": "4-3-3", "startXI": [], "substitutes": []}],  # bloco vazio
])
def test_escalacao_vazia_nao_e_escalacao(monkeypatch, resposta):
    """O caso perigoso: tratar "não saiu" como "ninguém foi escalado" anularia
    todos os picks da partida."""
    class _R:
        status_code = 200
        headers: dict = {}

        @staticmethod
        def json():
            return {"response": resposta}

    monkeypatch.setattr(ls.requests, "get", lambda *a, **k: _R())
    assert ls._buscar(123) is None


def test_erro_de_rede_nao_derruba_a_varredura(monkeypatch):
    def _explode(*a, **k):
        raise RuntimeError("timeout")
    monkeypatch.setattr(ls.requests, "get", _explode)
    assert ls._buscar(123) is None


# ── 2. quem é anulado, e como ───────────────────────────────────────────────
class _CursorFalso:
    def __init__(self, ids):
        self.ids = ids
        self.sql = None
        self.params = None

    def execute(self, sql, params=None):
        self.sql, self.params = sql, params

    def fetchall(self):
        return [{"id": i} for i in self.ids]


def test_quem_comeca_no_banco_nao_e_anulado():
    """A REGRA QUE ESTAVA ERRADA.

    O `_anular_fora_do_xi` recebe a RELAÇÃO INTEIRA (titulares + banco), e não
    só o XI. Passar só os titulares anularia todo reserva no instante em que a
    escalação sai · e reserva que entra e chuta faz o pick pagar.

    Quem está no banco e acaba não entrando é anulado DEPOIS do jogo, pelo
    caminho que já existia: sem folha do jogador, vira PUSH (routers/live.py).
    """
    fonte = open(os.path.join(_BACKEND, "lineups_sweep.py"), encoding="utf-8").read()
    bloco = fonte[fonte.index("anulados = _anular_fora_do_xi("):]
    bloco = bloco[:bloco.index("\n\n")]
    assert "titulares + reservas" in bloco, (
        "a anulação voltou a olhar só o XI inicial: reserva que entra em campo "
        "faz a aposta valer, e anular ali tira do usuário um pick que pagou")


def test_anula_como_push_e_avisa_quem_seguiu(monkeypatch):
    avisados = []
    import routers.live as live
    monkeypatch.setattr(live, "_sync_followed_result",
                        lambda pid, tipo, res, c: avisados.append((pid, tipo, res)))

    cur = _CursorFalso([41, 42])
    assert ls._anular_fora_do_xi(cur, 999, [1, 2, 3]) == 2

    assert "'PUSH'" in cur.sql and "profit = 0" in cur.sql
    assert cur.params[0] == ls.MOTIVO_FORA
    # A aposta seguida precisa ser liquidada junto: sem isso ela fica pendente
    # pra sempre, com a banca segurando uma entrada que a casa devolveu.
    assert avisados == [(41, "player_stats", "PUSH"), (42, "player_stats", "PUSH")]


def test_o_update_nunca_reescreve_resultado_ja_gravado():
    """Sem `result IS NULL` uma passada tardia viraria um GREEN liquidado em
    anulação · o pior tipo de bug, porque some com a evidência."""
    fonte = open(os.path.join(_BACKEND, "lineups_sweep.py"), encoding="utf-8").read()
    bloco = fonte[fonte.index("UPDATE picks_player_stats"):]
    bloco = bloco[:bloco.index('"""', 10)]
    assert "result IS NULL" in bloco
    assert "= ANY(%s)" in bloco, "a comparação com os titulares saiu do UPDATE"


# ── 3. os freios ────────────────────────────────────────────────────────────
def test_so_producao(monkeypatch):
    """A chave da API-Football é uma conta só pros três ambientes: dev varrendo
    sozinho gastaria a cota do site real. Mesmo gate de stats_sweep."""
    monkeypatch.delenv("LINEUP_SWEEP", raising=False)
    import runtime_env
    monkeypatch.setattr(runtime_env, "is_production", lambda: False)
    monkeypatch.setattr(runtime_env, "side_effects_enabled", lambda: True)
    assert ls._habilitada() is False

    monkeypatch.setattr(runtime_env, "is_production", lambda: True)
    assert ls._habilitada() is True

    # E o interruptor de emergência continua valendo em produção.
    monkeypatch.setenv("LINEUP_SWEEP", "off")
    assert ls._habilitada() is False


def test_a_fila_so_pega_pick_pendente_perto_do_jogo():
    """Três condições, e as três importam: pick ainda pendente, partida sem
    escalação oficial e dentro da janela do apito. Sem a janela, a varredura
    perguntaria a tarde inteira por um jogo da noite."""
    sql = ls._SQL_FILA
    assert "pp.result IS NULL" in sql
    assert "COALESCE(fl.oficial, FALSE) = FALSE" in sql
    assert "f.match_datetime BETWEEN" in sql
    # `match_date` é DATE pura: comparar hora com ela pegaria o dia inteiro.
    assert "pp.match_date BETWEEN" not in sql


def test_desiste_da_partida_que_o_provedor_nao_cobre():
    assert "tentativas" in ls._SQL_FILA
    assert ls._MAX_TENTATIVAS > 0


# ── 4. a tela recebe o estado ───────────────────────────────────────────────
def test_o_today_devolve_a_escalacao_de_graca():
    """O estado sai do banco, num CASE. Se a consulta da escalação fosse feita
    aqui, cada abertura da tela custaria uma chamada de API por partida."""
    fonte = open(os.path.join(_BACKEND, "routers", "suggestions.py"),
                 encoding="utf-8").read()
    bloco = fonte[fonte.index("def _juntar_escalacao"):]
    bloco = bloco[:bloco.index("def _get_user_banca")]
    for esperado in ("fixture_lineups", "'indefinida'", "'titular'", "'banco'",
                     "'fora'", "pp.void_reason"):
        assert esperado in bloco, f"sumiu da consulta de escalação: {esperado}"
    assert "requests" not in bloco


def test_a_lista_de_picks_nao_depende_da_escalacao():
    """A REGRESSÃO DE 02/09, travada.

    `_safe_query` devolve lista vazia quando qualquer coisa falha -- decisão
    certa pra "tabela que ainda não existe nesta instância", e desastrosa
    quando um campo opcional está DENTRO da consulta que traz os picks: com o
    JOIN em `fixture_lineups` e `void_reason` no SELECT, um backend sem a
    migration parou de mostrar QUALQUER pick de jogador, em silêncio, com os
    picks gravados no banco.

    A regra que fica: a consulta que lista os picks não menciona nada opcional.
    """
    fonte = open(os.path.join(_BACKEND, "routers", "suggestions.py"),
                 encoding="utf-8").read()
    bloco = fonte[fonte.index('result["player_stats"] = '):]
    bloco = bloco[:bloco.index("_juntar_escalacao(cur")]
    for proibido in ("fixture_lineups", "void_reason"):
        assert proibido not in bloco, (
            f"'{proibido}' voltou pra consulta dos picks: se a coluna ou a "
            "tabela faltar, a aba Jogadores fica vazia de novo")
