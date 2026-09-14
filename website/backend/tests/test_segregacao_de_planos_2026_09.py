"""A MATRIZ DE QUEM VÊ O QUÊ, com os cinco perfis de conta (14/09/2026).

Pedido dele: conferir se a segregação por plano está certa, com usuários de
planos diferentes, em vez de confiar em teste ponto a ponto.

O formato é de propósito uma TABELA. Os testes anteriores cobriam um gate de
cada vez, e foi assim que o Ao Vivo passou por três portas laterais em 10/09
(o sino, o `follow` e o mural) com o gate de leitura já no lugar: cada porta
tinha o seu próprio teste passando, e ninguém olhava as cinco linhas juntas.

Aqui, quando alguém mexer num gate, a coluna inteira muda e a tabela reprova.

A trava do conftest continua valendo: nada aqui abre conexão. `_pode_seguir`
recebe um cursor dublê, e os outros gates são função pura sobre um dict.
"""
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.append(str(_BACKEND))

FUTURO = "2099-01-01T00:00:00"
PASSADO = "2020-01-01T00:00:00"

#: As contas que existem de verdade no site, com o nome que elas têm na tela.
PERFIS = {
    "free":          {"id": 1, "plan": "free",  "plan_tier": "pro",  "plan_expires_at": None},
    "trial":         {"id": 2, "plan": "trial", "plan_tier": "base", "plan_expires_at": FUTURO},
    "pick_ia":       {"id": 3, "plan": "vip",   "plan_tier": "base", "plan_expires_at": FUTURO},
    "pick_ia_pro":   {"id": 4, "plan": "vip",   "plan_tier": "pro",  "plan_expires_at": FUTURO},
    "admin":         {"id": 5, "plan": "admin", "plan_tier": "base", "plan_expires_at": None},
    "pick_ia_venc":  {"id": 6, "plan": "vip",   "plan_tier": "base", "plan_expires_at": PASSADO},
    "pro_vencido":   {"id": 7, "plan": "vip",   "plan_tier": "pro",  "plan_expires_at": PASSADO},
    "trial_vencido": {"id": 8, "plan": "trial", "plan_tier": "pro",  "plan_expires_at": PASSADO},
    #: Quem assinou ANTES de 12/09 e nunca teve valor na coluna.
    "antigo":        {"id": 9, "plan": "vip",   "plan_expires_at": FUTURO},
}


class CursorFalso:
    """Só o suficiente pro `_pode_seguir`: ele consulta o Bingo liberado do dia
    e o Boost gratuito, e nenhum dos dois decide o que esta tabela mede."""

    def execute(self, sql, params=None):
        self._sql = " ".join(sql.split()).lower()

    def fetchone(self):
        return None


# ── quem é assinante, e quem tem o Pro ────────────────────────────────────
@pytest.mark.parametrize("perfil,assina,tem_pro", [
    ("free",          False, False),
    ("trial",         True,  True),   # o trial abre o Pro inteiro, de propósito
    ("pick_ia",       True,  False),
    ("pick_ia_pro",   True,  True),
    ("admin",         True,  True),   # admin nunca expira e vê tudo
    ("pick_ia_venc",  False, False),
    ("pro_vencido",   False, False),
    ("trial_vencido", False, False),
    ("antigo",        True,  True),   # tier ausente vale 'pro': não rebaixa
])
def test_os_dois_gates_por_perfil(perfil, assina, tem_pro):
    from auth_utils import is_vip_active, tem_tier_pro

    user = PERFIS[perfil]
    assert is_vip_active(user) is assina, f"{perfil}: is_vip_active"
    assert tem_tier_pro(user) is tem_pro, f"{perfil}: tem_tier_pro"


def test_ter_o_pro_nunca_vale_sem_ser_assinante():
    """A coluna nasce com DEFAULT 'pro' em TODA linha, free inclusive. Se algum
    gate um dia ler o tier sozinho, o site inteiro abre."""
    from auth_utils import is_vip_active, tem_tier_pro

    for nome, user in PERFIS.items():
        if tem_tier_pro(user):
            assert is_vip_active(user), f"{nome} tem Pro sem ser assinante"


# ── o produto Ao Vivo, que é o que separa os dois planos ──────────────────
@pytest.mark.parametrize("perfil,ve_ao_vivo", [
    ("free", False), ("trial", True), ("pick_ia", False),
    ("pick_ia_pro", True), ("admin", True), ("pro_vencido", False),
])
class TestOAoVivoSegueOTier:
    def test_o_gate_das_rotas(self, perfil, ve_ao_vivo):
        from auth_utils import require_pro

        user = PERFIS[perfil]
        try:
            require_pro(user)
            passou = True
        except HTTPException:
            passou = False
        assert passou is ve_ao_vivo, f"{perfil}: require_pro"

    def test_seguir_pick_ao_vivo(self, perfil, ve_ao_vivo):
        """Seguir é ler: o teaser entrega o id, e a Banca devolveria mercado,
        linha e odd de tudo que a pessoa segue."""
        from routers.banca import _pode_seguir

        assert _pode_seguir(CursorFalso(), PERFIS[perfil], "live", 1) is ve_ao_vivo

    def test_o_mural_do_pick_ao_vivo(self, perfil, ve_ao_vivo):
        """Comentário de pick trancado cita mercado e linha o tempo todo."""
        from routers.social import _pode_ver_social

        assert _pode_ver_social("live", PERFIS[perfil]) is ve_ao_vivo


# ── os produtos de pré-jogo, que os DOIS planos abrem ─────────────────────
@pytest.mark.parametrize("pick_type", [
    "vip", "multipla", "bingo", "alavancagem", "faltas", "goleiros",
    "player_stats",
])
@pytest.mark.parametrize("perfil,abre", [
    ("free", False), ("trial", True), ("pick_ia", True),
    ("pick_ia_pro", True), ("admin", True), ("pick_ia_venc", False),
])
def test_o_pre_jogo_nao_distingue_os_dois_planos(pick_type, perfil, abre):
    """É o ponto inteiro do desenho: o assinante de entrada paga e leva TODO o
    pré-jogo. Se um destes virar False pro `pick_ia`, a coluna `plan_tier`
    vazou pra um gate que não devia lê-la."""
    from routers.banca import _pode_seguir

    # O Bingo tem um gate de produto próprio (feature_flags) que não é plano.
    if pick_type == "bingo":
        from feature_flags import BINGO_BETA_ADMIN_ONLY
        if BINGO_BETA_ADMIN_ONLY and perfil != "admin":
            pytest.skip("Bingo em teste restrito a admin")

    assert _pode_seguir(CursorFalso(), PERFIS[perfil], pick_type, 1) is abre


@pytest.mark.parametrize("perfil,abre", [
    ("free", True), ("pick_ia", True), ("pick_ia_pro", True), ("admin", True),
])
def test_o_que_e_aberto_continua_aberto(perfil, abre):
    """A dica do dia e o mural dela não podem ter sido fechados sem querer:
    o Free é a isca de aquisição."""
    from routers.social import _pode_ver_social

    assert _pode_ver_social("free", PERFIS[perfil]) is abre


# ── o sino, que entrega o CORPO do aviso ──────────────────────────────────
def test_as_clausulas_sql_espelham_os_gates_python():
    """O aviso em massa não passa por usuário nenhum: nasce de um SELECT. Se a
    cláusula divergir do gate, o sino vira a porta dos fundos do paywall, que
    foi exatamente o achado de 10/09."""
    from routers.notifications import SQL_PRO_ATIVO, SQL_VIP_ATIVO

    vip = " ".join(SQL_VIP_ATIVO.split())
    pro = " ".join(SQL_PRO_ATIVO.split())

    # Mesma lista de planos e mesma leitura de vencimento nos dois.
    for sql in (vip, pro):
        assert "u.plan IN ('vip', 'trial', 'admin')" in sql
        assert "u.expires_at IS NULL OR u.expires_at > NOW()" in sql
        assert "u.plan = 'admin' OR" in sql

    # E só o do Pro cobra o tier, só de quem paga em 'vip'.
    assert "plan_tier" not in vip, "o gate de assinante não pode ler o tier"
    assert "COALESCE(u.plan_tier, 'pro') = 'pro'" in pro
    assert "u.plan <> 'vip' OR" in pro, "admin e trial não podem ser cortados"


def test_o_aviso_de_pick_ao_vivo_usa_o_alcance_do_pro():
    from pathlib import Path

    src = (_BACKEND / "routers" / "notifications.py").read_text(encoding="utf-8")
    trecho = src[src.index("def notificar_pick_live_novo"):]
    trecho = trecho[:trecho.index("LIVE_NOVO_JANELA_MIN")]
    assert "notify_pro_users(" in trecho
    assert "notify_vip_users(" not in trecho
    assert "notify_all_users(" not in trecho


# ── o agente de chat, o outro exclusivo do Pro ────────────────────────────
def test_o_chat_separa_os_tres_casos():
    """free -> FAQ e convite pra assinar; Pick IA -> convite de upgrade;
    Pro -> o agente. Três respostas, e não duas."""
    src = (_BACKEND / "routers" / "chat.py").read_text(encoding="utf-8")
    assert "if not is_vip_active(current_user):" in src
    assert "if not tem_tier_pro(current_user):" in src
    assert "_UPGRADE_PRO" in src
    # O free nunca pode cair no recado de upgrade: ele não tem o que subir.
    i_vip = src.index("if not is_vip_active(current_user):")
    i_pro = src.index("if not tem_tier_pro(current_user):")
    assert i_vip < i_pro, "a checagem de assinatura tem que vir primeiro"
