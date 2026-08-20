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


# ─────────────────── Fim do teste grátis · 2026-08-20 ───────────────────
#
# O aviso de faixa acima cobre o plano PERTO de vencer e sai de cena quando o
# prazo passa. Estes cobrem a outra ponta: o teste acabou, a pessoa não
# assinou, e o site precisa avisar UMA vez.


class _CurFake:
    """Cursor de mentira: registra os SQL e finge a tabela de notificações."""

    def __init__(self):
        self.sqls: list = []
        self.notificacoes: list = []
        self._ultimo = None

    def execute(self, sql, params=None):
        self.sqls.append((" ".join(sql.split()), params))
        if "INSERT INTO notifications" in sql:
            self.notificacoes.append(params)
        self._ultimo = None

    def fetchone(self):
        return self._ultimo


def _conta(plan, dias_de_vencimento):
    from datetime import timedelta
    return {
        "id": 7,
        "plan": plan,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=dias_de_vencimento),
    }


def test_trial_vencido_rebaixa_para_free_e_avisa():
    from plan_expiry import DEDUPE_TRIAL_ENCERRADO, expirar_plano_vencido

    cur = _CurFake()
    user = _conta("trial", -1)

    assert expirar_plano_vencido(cur, user) is True
    assert user["plan"] == "free" and user["expires_at"] is None
    assert any("UPDATE users SET plan='free'" in s for s, _ in cur.sqls)
    assert len(cur.notificacoes) == 1
    assert DEDUPE_TRIAL_ENCERRADO in cur.notificacoes[0]


def test_trial_dentro_do_prazo_nao_mexe_em_nada():
    """O aviso é do FIM do teste. Disparar antes seria pedir assinatura de
    quem ainda está usando o que ganhou."""
    from plan_expiry import expirar_plano_vencido

    cur = _CurFake()
    user = _conta("trial", 1)

    assert expirar_plano_vencido(cur, user) is False
    assert user["plan"] == "trial"
    assert cur.sqls == [] and cur.notificacoes == []


def test_vip_vencido_rebaixa_mas_nao_manda_o_aviso_de_teste():
    """VIP vencido é renovação, não fim de teste · são mensagens diferentes e
    a de renovação já existe (aviso de faixa)."""
    from plan_expiry import expirar_plano_vencido

    cur = _CurFake()
    user = _conta("vip", -1)

    assert expirar_plano_vencido(cur, user) is True
    assert user["plan"] == "free"
    assert cur.notificacoes == [], "VIP recebeu o popup de fim de teste"


def test_free_nao_entra_no_rebaixamento():
    from plan_expiry import expirar_plano_vencido

    cur = _CurFake()
    user = {"id": 7, "plan": "free", "expires_at": None}

    assert expirar_plano_vencido(cur, user) is False
    assert cur.sqls == []


def test_chave_do_aviso_e_fixa_para_valer_uma_vez_so():
    """É o que garante o 'uma única vez por usuário' pedido pelo produto:
    `notifications` tem UNIQUE (user_id, dedupe_key), então uma chave sem data
    não tem como criar uma segunda linha. Se alguém colocar data/plano aqui,
    o popup volta a poder aparecer duas vezes."""
    from plan_expiry import DEDUPE_TRIAL_ENCERRADO

    assert DEDUPE_TRIAL_ENCERRADO == "trial_encerrado"
    assert ":" not in DEDUPE_TRIAL_ENCERRADO


def test_falha_ao_notificar_nao_impede_o_rebaixamento():
    """Esta função roda pendurada no login. Derrubar a entrada da pessoa por
    causa de um aviso é a troca errada."""
    from plan_expiry import expirar_plano_vencido

    class CurQuebrado(_CurFake):
        def execute(self, sql, params=None):
            if "INSERT INTO notifications" in sql:
                raise RuntimeError("banco caiu no meio")
            super().execute(sql, params)

    cur = CurQuebrado()
    user = _conta("trial", -1)

    assert expirar_plano_vencido(cur, user) is True
    assert user["plan"] == "free"


def test_as_tres_rotas_usam_a_funcao_unica():
    """Login, refresh e /auth/me tinham três cópias do mesmo if. A terceira a
    ganhar responsabilidade nova seria a que ficaria pra trás em silêncio · e
    a que ficasse rebaixaria a conta sem nunca oferecer a assinatura."""
    import re
    from tests.test_home_2026_08 import _fonte

    fonte = _fonte("routers/auth.py")
    assert len(re.findall(r"expirar_plano_vencido\(cur, ", fonte)) == 3
    assert "UPDATE users SET plan='free', expires_at=NULL" not in fonte, \
        "voltou a rebaixar na mão em routers/auth.py"


def test_popup_do_fim_do_teste_esta_ligado_no_front():
    """O aviso precisa CHEGAR na tela, não só existir no banco.

    Três pontas, e cada uma sozinha é silenciosa se faltar: o tipo tem que
    existir no contexto (senão a notificação nunca vira `pendingTrialEnded`),
    o GlobalModals tem que renderizar o modal, e fechar tem que marcar como
    lida (senão ele reabre a cada visita e o "uma vez só" morre no front,
    mesmo com o servidor certo).
    """
    from tests.test_home_2026_08 import _front

    ctx = _front("context/NotificationContext.tsx")
    assert "'trial_ended'" in ctx, "tipo novo nao entrou na uniao do contexto"
    assert "pendingTrialEnded" in ctx

    modais = _front("components/GlobalModals.tsx")
    assert "TrialEndedModal" in modais
    assert "markRead" in modais, "fechar o modal nao marca a notificacao como lida"

    # Um modal por vez: o fechamento mensal pede AÇÃO (confirmar a banca) e tem
    # prioridade; este e' convite e espera a vez. Sem isso os dois abrem juntos,
    # um por cima do outro.
    assert "!monthlyCloseOpen" in modais


def test_icone_do_sino_cobre_o_tipo_novo():
    """Tipo sem ícone cai no padrão (certo/errado de pick), e o item do sino
    passaria a dizer 'green' visualmente pra um aviso de plano."""
    from tests.test_home_2026_08 import _front

    sino = _front("components/NotificationBell.tsx")
    assert "n.type === 'trial_ended'" in sino
