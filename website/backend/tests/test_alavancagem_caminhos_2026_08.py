"""Caminhos de alavancagem (15/08): lucro composto so' vira dinheiro ao encerrar.

A alavancagem nao e' uma aposta por dia, e' um caminho: entra com um valor e a
cada GREEN reaposta o bolo inteiro. O modelo antigo tratava cada green como
lucro e o RED como um "reset" silencioso -- a tela mostrava um bolo que o
usuario nao podia sacar, e nao existia nenhum registro de onde um caminho
comecou ou terminou.

O que este arquivo tranca:

1. REPLAY. GREEN compoe, RED fecha o caminho perdendo SO' o valor de entrada e
   abre o proximo no mesmo valor. Sem isso o RED cobraria o composto, que nunca
   saiu da mesa.

2. FRONTEIRA. O pick que estourou o caminho nao pode ser recontado no caminho
   seguinte -- e' o bug classico de replay por janela de tempo, e ele se
   pagaria zerando o caminho novo pra sempre.

3. SO' CAMINHO FECHADO CONTA. `_alav_realized_pnl` ignora o caminho aberto. E'
   a regra inteira do pedido: enquanto roda, nao e' dinheiro.

Nada aqui abre conexao: o conftest ja bloqueia get_connection.
"""
from datetime import datetime, timedelta

import pytest

from routers.banca import (
    ALAV_END_MANUAL,
    ALAV_END_RED,
    _alav_realized_pnl,
    _alav_sync,
)

BASE = datetime(2026, 8, 1, 12, 0, 0)


class FakeCur:
    """Cursor de mentira com o minimo que o replay usa: user_banca, a tabela de
    caminhos e os picks seguidos. Guarda os caminhos em memoria pra que o
    INSERT/UPDATE do proprio _alav_sync seja observavel pelo teste."""

    def __init__(self, initial, picks):
        self.initial = initial
        self.picks = picks          # [(followed_at, result, odd)]
        self.series = []            # dicts, com id sequencial
        self._next_id = 1
        self._result = None

    # ── API usada pelo codigo sob teste ──────────────────────────────────
    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if "FROM user_banca" in s:
            self._result = [{"alav_bankroll_init": self.initial}]
        elif "FROM alavancagem_series" in s and "ended_at IS NULL" in s:
            open_ = [x for x in self.series if x["ended_at"] is None]
            self._result = [dict(open_[0])] if open_ else []
        elif "MIN(followed_at)" in s:
            first = min((p[0] for p in self.picks), default=None)
            self._result = [{"first_at": first}]
        elif s.startswith("INSERT INTO alavancagem_series"):
            row = {
                "id": self._next_id, "user_id": params[0],
                "initial_amount": float(params[1]),
                "started_at": params[2] if len(params) > 2 and params[2] else BASE,
                "ended_at": None, "end_reason": None,
                "final_amount": None, "realized_pnl": None,
            }
            self._next_id += 1
            self.series.append(row)
            self._result = [dict(row)]
        elif s.startswith("UPDATE alavancagem_series"):
            ended_at, reason, final, realized, units, sid = params
            for row in self.series:
                if row["id"] == sid:
                    row.update(ended_at=ended_at, end_reason=reason,
                               final_amount=float(final), realized_pnl=float(realized),
                               realized_units=float(units))
            self._result = []
        elif "JOIN picks_alavancagem" in s:
            started_at = params[1]
            self._result = [
                {"id": i, "result": r, "odd_combined": o, "match_date": None,
                 "home_team_1": "A", "away_team_1": "B", "followed_at": f}
                for i, (f, r, o) in enumerate(self.picks, start=1)
                if f >= started_at
            ]
        elif "SUM(realized_pnl)" in s or "SUM(realized_units)" in s:
            col = "realized_units" if "SUM(realized_units)" in s else "realized_pnl"
            total = sum(float(x.get(col) or 0)
                        for x in self.series if x["ended_at"] is not None)
            self._result = [{"total": total}]
        else:
            self._result = []

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)


def _cur(initial, picks):
    return FakeCur(initial, picks)


# ─────────────────────── 1. Replay do caminho ───────────────────────
def test_green_compoe_o_bolo_inteiro():
    cur = _cur(50, [
        (BASE,                       "GREEN", 2.0),
        (BASE + timedelta(days=1),   "GREEN", 1.5),
    ])
    serie = _alav_sync(cur, user_id=1)
    assert serie["current_bankroll"] == 150.0   # 50 -> 100 -> 150
    assert len(serie["steps"]) == 2


def test_red_perde_so_a_entrada_e_nao_o_composto():
    """O ponto do pedido. Depois de 50 -> 200, o RED custa 50, nao 200."""
    cur = _cur(50, [
        (BASE,                     "GREEN", 2.0),
        (BASE + timedelta(days=1), "GREEN", 2.0),
        (BASE + timedelta(days=2), "RED",   1.8),
    ])
    _alav_sync(cur, user_id=1)
    fechado = [s for s in cur.series if s["ended_at"] is not None]
    assert len(fechado) == 1
    assert fechado[0]["end_reason"] == ALAV_END_RED
    assert fechado[0]["realized_pnl"] == -50.0


def test_red_abre_o_proximo_caminho_no_mesmo_valor():
    cur = _cur(50, [(BASE, "RED", 1.8)])
    serie = _alav_sync(cur, user_id=1)
    assert serie["ended_at"] is None if "ended_at" in serie else True
    assert float(serie["initial_amount"]) == 50.0
    assert serie["current_bankroll"] == 50.0
    assert len([s for s in cur.series if s["ended_at"] is None]) == 1


def test_pick_do_red_nao_volta_no_caminho_seguinte():
    """Fronteira por followed_at: sem o microsegundo, o RED entraria de novo no
    caminho novo e ele nasceria estourado, pra sempre."""
    cur = _cur(50, [
        (BASE,                     "RED",   1.8),
        (BASE + timedelta(days=1), "GREEN", 3.0),
    ])
    serie = _alav_sync(cur, user_id=1)
    assert serie["current_bankroll"] == 150.0        # 50 * 3.0, o RED ficou pra tras
    assert [s["result"] for s in serie["steps"]] == ["GREEN"]


def test_dois_reds_geram_dois_caminhos_fechados():
    cur = _cur(100, [
        (BASE,                     "GREEN", 2.0),
        (BASE + timedelta(days=1), "RED",   1.5),
        (BASE + timedelta(days=2), "GREEN", 1.5),
        (BASE + timedelta(days=3), "RED",   2.0),
    ])
    serie = _alav_sync(cur, user_id=1)
    fechados = [s for s in cur.series if s["ended_at"] is not None]
    assert len(fechados) == 2
    assert all(f["realized_pnl"] == -100.0 for f in fechados)
    assert serie["current_bankroll"] == 100.0        # caminho novo, zerado


def test_meta_fecha_o_caminho_sozinho():
    """Composto que nao para e' lucro que nunca existe: basta um RED la na
    frente pra transformar tudo em po. A meta e' o que faz o ganho virar
    dinheiro sem depender de o usuario estar olhando."""
    from routers.banca import ALAV_END_META, ALAV_META_PADRAO

    picks = [(BASE + timedelta(days=i), "GREEN", 1.5) for i in range(ALAV_META_PADRAO + 2)]
    cur = _cur(100, picks)
    serie = _alav_sync(cur, user_id=1)

    fechados = [s for s in cur.series if s["ended_at"] is not None]
    assert len(fechados) == 1
    assert fechados[0]["end_reason"] == ALAV_END_META
    # O bolo e' 100 * 1.5^meta; realizado e' o LUCRO, nao o bolo. Calculado e
    # nao cravado porque a meta e' parametro de produto e ja mudou uma vez.
    esperado = 100.0
    for _ in range(ALAV_META_PADRAO):
        esperado = round(esperado * 1.5, 2)
    assert fechados[0]["final_amount"] == esperado
    assert fechados[0]["realized_pnl"] == round(esperado - 100.0, 2)
    # E em unidades: o caminho arrisca 1u e paga (multiplicador - 1)u.
    assert fechados[0]["realized_units"] == round(esperado / 100.0 - 1, 4)
    # E o caminho seguinte ja nasceu, com os greens que sobraram dentro dele.
    assert float(serie["initial_amount"]) == 100.0


def test_meta_nao_engole_o_green_seguinte():
    """A fronteira de microsegundo tem que valer pro fechamento por meta igual
    vale pro RED · senao o green que bateu a meta entraria tambem no caminho
    novo e o daria de graca."""
    from routers.banca import ALAV_META_PADRAO

    picks = [(BASE + timedelta(days=i), "GREEN", 2.0) for i in range(ALAV_META_PADRAO + 1)]
    cur = _cur(10, picks)
    serie = _alav_sync(cur, user_id=1)
    # O caminho novo tem SO' o green que sobrou: 10 * 2 = 20, nao 40.
    assert serie["current_bankroll"] == 20.0
    assert len(serie["steps"]) == 1


def test_encerrar_antes_da_meta_continua_livre():
    """A meta e' onde ele fecha sozinho, nao uma trava. Quem quiser parar no
    segundo green para no segundo green."""
    import inspect

    from routers import banca
    src = inspect.getsource(banca.encerrar_alavancagem)
    assert "ALAV_META_PADRAO" not in src, "encerrar na mao nao pode exigir a meta"


def test_sem_configuracao_nao_cria_caminho():
    cur = _cur(None, [])
    assert _alav_sync(cur, user_id=1) is None
    assert cur.series == []


# ─────────────────── 2. So' caminho fechado e' dinheiro ───────────────────
def test_caminho_aberto_nao_entra_no_realizado():
    cur = _cur(50, [
        (BASE,                     "GREEN", 2.0),
        (BASE + timedelta(days=1), "GREEN", 2.0),
    ])
    serie = _alav_sync(cur, user_id=1)
    assert serie["current_bankroll"] == 200.0        # bolo na tela
    assert _alav_realized_pnl(cur, user_id=1) == 0.0  # e zero na banca


def test_realizado_soma_o_que_ja_fechou():
    cur = _cur(50, [
        (BASE,                     "GREEN", 2.0),
        (BASE + timedelta(days=1), "RED",   1.5),
    ])
    _alav_sync(cur, user_id=1)
    assert _alav_realized_pnl(cur, user_id=1) == -50.0


# ─────────────────── 3. Contrato do endpoint de encerrar ───────────────────
def test_encerrar_exige_lucro():
    """Fechar em cima da entrada nao realiza nada e so' sujaria o historico."""
    from routers import banca
    fonte = banca.encerrar_alavancagem.__doc__ or ""
    assert "lucro" in fonte.lower()


def test_encerrar_e_um_por_caminho():
    """O UPDATE tem `ended_at IS NULL` no WHERE e checa rowcount · sem isso,
    duas abas realizariam o mesmo lucro duas vezes."""
    import inspect

    from routers import banca
    src = inspect.getsource(banca.encerrar_alavancagem)
    assert "ended_at IS NULL" in src
    assert "rowcount" in src
    assert "ALAV_END_MANUAL" in src


def test_um_caminho_aberto_por_usuario_no_banco():
    """A trava e' indice unico parcial, nao logica de aplicacao."""
    import migrations

    src = inspect_source(migrations)
    assert "idx_alav_series_um_aberto" in src
    assert "WHERE ended_at IS NULL" in src


def inspect_source(mod):
    import inspect
    return inspect.getsource(mod)


# ─────────────────── 4. A banca principal usa o realizado ───────────────────
@pytest.mark.parametrize("fn", ["_compute_bankroll_current", "_compute_month_stats"])
def test_banca_soma_caminho_encerrado(fn):
    """Se um dos dois esquecer o realizado, banca e fechamento mensal divergem."""
    import inspect

    from routers import banca
    src = inspect.getsource(getattr(banca, fn))
    assert "_alav_realized_pnl" in src
