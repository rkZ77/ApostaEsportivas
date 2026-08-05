"""Aviso de plano perto de vencer: contagem de dias, faixas e disparo único.

O que estes testes protegem é o que a leitura do código não garante sozinha:
que a mesma pessoa não recebe o mesmo e-mail a cada login, e que o trial não
recebe o texto de renovação de assinatura.
"""
from datetime import datetime, timedelta, timezone

import pytest

from plan_expiry import (
    avisar_plano_expirando,
    dias_restantes,
    faixa_do_aviso,
)

AGORA = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


def _daqui(dias: float) -> datetime:
    return AGORA + timedelta(days=dias)


class CursorFalso:
    """Só o suficiente pro módulo: guarda o que foi inserido e responde se a
    dedupe_key já existe. Sem banco · o que está em teste é a decisão."""

    def __init__(self):
        self.chaves: set[str] = set()
        self.inseridos: list[tuple] = []
        self._ultimo_select = None

    def execute(self, sql, params=None):
        sql_limpo = " ".join(sql.split()).lower()
        if sql_limpo.startswith("select 1 from notifications"):
            self._ultimo_select = params[1] in self.chaves
        elif "insert into notifications" in sql_limpo:
            self.chaves.add(params[-1])
            self.inseridos.append(params)

    def fetchone(self):
        return (1,) if self._ultimo_select else None


def _usuario(plan="vip", dias=2):
    return {"id": 7, "name": "Fulano de Tal", "email": "fulano@exemplo.com",
            "plan": plan, "expires_at": _daqui(dias)}


# ── contagem ──────────────────────────────────────────────────────────────
def test_trunca_para_baixo():
    """Faltando 1,9 dia a pessoa está no último dia cheio · arredondar pra
    cima daria uma folga que ela não tem."""
    assert dias_restantes(_daqui(1.9), agora=AGORA) == 1


def test_sem_data_nao_conta():
    assert dias_restantes(None, agora=AGORA) is None


@pytest.mark.parametrize("dias,esperada", [(0, 0), (1, 1), (2, 3), (3, 3), (4, None), (10, None)])
def test_faixas(dias, esperada):
    assert faixa_do_aviso(dias) == esperada


# ── disparo ───────────────────────────────────────────────────────────────
def test_avisa_uma_vez_por_faixa_mesmo_com_varios_logins():
    """O caso que motivou a dedupe: quem entra três vezes por dia não pode
    receber três e-mails."""
    cur, enviados = CursorFalso(), []
    user = _usuario(dias=2)

    primeiro = avisar_plano_expirando(cur, user, "https://x", enviar_email=lambda *a: enviados.append(a), agora=AGORA)
    segundo = avisar_plano_expirando(cur, user, "https://x", enviar_email=lambda *a: enviados.append(a), agora=AGORA)

    assert primeiro is not None
    assert segundo is None
    assert len(enviados) == 1


def test_faixa_mais_apertada_avisa_de_novo():
    """Avisado com 3 dias, a pessoa precisa ser avisada de novo no último dia."""
    cur, enviados = CursorFalso(), []
    user = _usuario(dias=3)

    avisar_plano_expirando(cur, user, "https://x", enviar_email=lambda *a: enviados.append(a), agora=AGORA)
    user_hoje = {**user, "expires_at": _daqui(3)}
    avisar_plano_expirando(cur, user_hoje, "https://x", enviar_email=lambda *a: enviados.append(a),
                           agora=AGORA + timedelta(days=3))

    assert len(enviados) == 2


def test_longe_do_vencimento_nao_avisa():
    cur = CursorFalso()
    assert avisar_plano_expirando(cur, _usuario(dias=10), "https://x", agora=AGORA) is None
    assert cur.inseridos == []


def test_plano_free_nao_avisa():
    cur = CursorFalso()
    assert avisar_plano_expirando(cur, {**_usuario(), "plan": "free"}, "https://x", agora=AGORA) is None


def test_vencido_nao_avisa():
    """O login já rebaixa pra free antes disto · oferecer renovação de algo que
    a pessoa perdeu é outra conversa, não este aviso."""
    cur = CursorFalso()
    assert avisar_plano_expirando(cur, _usuario(dias=-1), "https://x", agora=AGORA) is None


def test_sem_funcao_de_email_ainda_notifica():
    """É o modo do staging: sino sim, e-mail real não."""
    cur = CursorFalso()
    assert avisar_plano_expirando(cur, _usuario(dias=1), "https://x", agora=AGORA) is not None
    assert len(cur.inseridos) == 1


# ── texto ─────────────────────────────────────────────────────────────────
def test_nome_do_plano_aparece_no_titulo():
    cur, enviados = CursorFalso(), []
    avisar_plano_expirando(cur, _usuario("vip", 0), "https://x", enviar_email=lambda *a: enviados.append(a), agora=AGORA)

    assert "Plano VIP" in enviados[0][1]
    assert "expira hoje" in enviados[0][1]


def test_trial_tem_rotulo_e_texto_proprios():
    cur, enviados = CursorFalso(), []
    avisar_plano_expirando(cur, _usuario("trial", 1), "https://x", enviar_email=lambda *a: enviados.append(a), agora=AGORA)

    assunto, corpo = enviados[0][1], enviados[0][2]
    assert "Teste grátis" in assunto
    assert "expira amanhã" in assunto
    assert "volta pro plano free" in corpo
