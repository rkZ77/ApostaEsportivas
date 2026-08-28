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


@pytest.mark.parametrize("horas,esperada", [
    (0, 6), (5, 6), (20, 24), (24, 24), (48, 72), (72, 72), (73, None), (240, None),
])
def test_faixas_do_vip(horas, esperada):
    assert faixa_do_aviso(horas, "vip") == esperada


@pytest.mark.parametrize("horas,esperada", [
    (0, 6), (5, 6), (20, 24), (24, 24), (25, None), (47, None),
])
def test_faixas_do_teste(horas, esperada):
    """O teste dura 2 dias · uma faixa de 3 dias nasceria vencida nele."""
    assert faixa_do_aviso(horas, "trial") == esperada


def test_teste_recem_criado_nao_avisa_nada():
    """O DEFEITO QUE ISTO TRAVA (28/08/2026).

    O aviso saía no instante em que o teste era criado. Faltando 47h59, o
    truncamento pra dia dava `1`, a faixa mais distante era 3 DIAS, e 1 <= 3
    disparava o e-mail ali mesmo: a pessoa confirmava o e-mail, ganhava o
    teste e recebia na mesma hora um aviso de que ele estava acabando.
    """
    cur, enviados = CursorFalso(), []
    recem = {**_usuario("trial"), "expires_at": AGORA + timedelta(days=2, seconds=-1)}

    resultado = avisar_plano_expirando(
        cur, recem, "https://x", enviar_email=lambda *a: enviados.append(a), agora=AGORA)

    assert resultado is None
    assert cur.inseridos == []
    assert enviados == []


def test_teste_avisa_faltando_um_dia():
    """O aviso que o usuário pediu · um dia inteiro antes de acabar."""
    cur, enviados = CursorFalso(), []
    user = {**_usuario("trial"), "expires_at": AGORA + timedelta(hours=23)}

    assert avisar_plano_expirando(
        cur, user, "https://x", enviar_email=lambda *a: enviados.append(a),
        agora=AGORA) is not None
    assert "Teste grátis" in enviados[0][1]


def test_vip_recem_assinado_nao_avisa():
    """Mesma armadilha do teste, do outro lado: assinar não é vencer."""
    cur = CursorFalso()
    user = {**_usuario("vip"), "expires_at": AGORA + timedelta(days=30)}
    assert avisar_plano_expirando(cur, user, "https://x", agora=AGORA) is None


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


# ────────────────── Fim do acesso · 2026-08-20 e 2026-08-23 ──────────────────
#
# O aviso de faixa acima cobre o plano PERTO de vencer e sai de cena quando o
# prazo passa. Estes cobrem a outra ponta: o acesso acabou e o site precisa
# avisar. Nasceu só pro teste grátis (20/08); o VIP vencido entrou em 23/08,
# porque ser rebaixado em silêncio era o que acontecia com quem tinha pagado.


class _CurFake:
    """Cursor de mentira: registra os SQL e finge a tabela de notificações,
    inclusive o UNIQUE (user_id, dedupe_key) que decide se o e-mail sai."""

    def __init__(self):
        self.sqls: list = []
        self.notificacoes: list = []
        self.chaves: set = set()
        self._ultimo = None

    def execute(self, sql, params=None):
        limpo = " ".join(sql.split())
        self.sqls.append((limpo, params))
        if "INSERT INTO notifications" in limpo:
            self.notificacoes.append(params)
            self.chaves.add(params[-1])
            self._ultimo = None
        elif limpo.lower().startswith("select 1 from notifications"):
            self._ultimo = (1,) if params[1] in self.chaves else None
        else:
            self._ultimo = None

    def fetchone(self):
        return self._ultimo


def _conta(plan, dias_de_vencimento):
    from datetime import timedelta
    return {
        "id": 7,
        "name": "Fulano de Tal",
        "email": "fulano@exemplo.com",
        "plan": plan,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=dias_de_vencimento),
    }


def _chave_da_notificacao(cur) -> str:
    """A dedupe_key é o último parâmetro do INSERT (ver create_notification)."""
    return cur.notificacoes[0][-1]


def test_trial_vencido_rebaixa_para_free_e_avisa():
    from plan_expiry import DEDUPE_TRIAL_ENCERRADO, expirar_plano_vencido

    cur = _CurFake()
    user = _conta("trial", -1)

    assert expirar_plano_vencido(cur, user) is True
    assert user["plan"] == "free" and user["expires_at"] is None
    assert any("UPDATE users SET plan='free'" in s for s, _ in cur.sqls)
    assert len(cur.notificacoes) == 1
    assert _chave_da_notificacao(cur) == DEDUPE_TRIAL_ENCERRADO


def test_trial_dentro_do_prazo_nao_mexe_em_nada():
    """O aviso é do FIM do acesso. Disparar antes seria pedir assinatura de
    quem ainda está usando o que ganhou."""
    from plan_expiry import expirar_plano_vencido

    cur = _CurFake()
    user = _conta("trial", 1)

    assert expirar_plano_vencido(cur, user) is False
    assert user["plan"] == "trial"
    assert cur.sqls == [] and cur.notificacoes == []


def test_vip_vencido_tambem_avisa():
    """Até 23/08/2026 o VIP era rebaixado em silêncio · o argumento era que
    renovação já tinha o aviso de faixa, mas aquele aviso é de ANTES e quem
    não entrou no site naqueles três dias não leu nenhum dos dois."""
    from plan_expiry import expirar_plano_vencido

    cur = _CurFake()
    user = _conta("vip", -1)

    assert expirar_plano_vencido(cur, user) is True
    assert user["plan"] == "free" and user["expires_at"] is None
    assert len(cur.notificacoes) == 1, "assinante rebaixado sem receber nada"
    assert "vip_ended" in cur.notificacoes[0]


def test_os_dois_finais_falam_verbos_diferentes():
    """Quem testou ASSINA, quem assinou RENOVA. Texto único aqui era pedir
    assinatura a quem já tinha assinado."""
    from plan_expiry import ENCERRAMENTO

    titulo_t, corpo_t, cta_t = ENCERRAMENTO["trial"]
    titulo_v, corpo_v, cta_v = ENCERRAMENTO["vip"]

    assert "teste" in titulo_t.lower() and "vip" in titulo_v.lower()
    assert "Assine" in corpo_t and "Assinar" in cta_t
    assert "Renove" in corpo_v and "Renovar" in cta_v


def test_free_nao_entra_no_rebaixamento():
    from plan_expiry import expirar_plano_vencido

    cur = _CurFake()
    user = {"id": 7, "plan": "free", "expires_at": None}

    assert expirar_plano_vencido(cur, user) is False
    assert cur.sqls == []


def test_chave_do_teste_e_fixa_para_valer_uma_vez_so():
    """É o que garante o 'uma única vez por usuário' pedido pelo produto:
    `notifications` tem UNIQUE (user_id, dedupe_key), então uma chave sem data
    não tem como criar uma segunda linha. Se alguém colocar data/plano aqui,
    o popup volta a poder aparecer duas vezes."""
    from plan_expiry import DEDUPE_TRIAL_ENCERRADO

    assert DEDUPE_TRIAL_ENCERRADO == "trial_encerrado"
    assert ":" not in DEDUPE_TRIAL_ENCERRADO


def test_chave_do_vip_muda_a_cada_ciclo():
    """O oposto da regra do teste, e de propósito. VIP vence uma vez por ciclo:
    com chave fixa, a segunda expiração cairia no ON CONFLICT DO UPDATE, que
    preserva `read_at` · a notificação voltaria já lida e o popup nunca mais
    abriria pra quem assinou de novo e deixou vencer de novo."""
    from datetime import date

    from plan_expiry import dedupe_vip_encerrado

    assert dedupe_vip_encerrado(date(2026, 8, 23)) != dedupe_vip_encerrado(date(2026, 9, 23))
    assert dedupe_vip_encerrado(date(2026, 8, 23)).startswith("vip_encerrado:")


def test_chave_do_vip_carrega_a_data_do_vencimento():
    from plan_expiry import dedupe_vip_encerrado, expirar_plano_vencido

    cur = _CurFake()
    user = _conta("vip", -1)
    esperada = dedupe_vip_encerrado(user["expires_at"].date())

    expirar_plano_vencido(cur, user)
    assert _chave_da_notificacao(cur) == esperada


def test_falha_ao_notificar_nao_impede_o_rebaixamento():
    """Esta função roda pendurada no login e no /auth/me. Derrubar a entrada da
    pessoa por causa de um aviso é a troca errada."""
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


# ── o e-mail do encerramento ─────────────────────────────────────────────────
#
# O sino só alcança quem volta ao site, e quem acabou de perder acesso é
# justamente quem pode não voltar. Até 23/08/2026 este e-mail não existia.

def _expira_com_email(plan):
    from plan_expiry import expirar_plano_vencido

    enviados = []
    cur = _CurFake()
    expirar_plano_vencido(cur, _conta(plan, -1),
                          enviar_email=lambda *a: enviados.append(a),
                          site_url="https://x")
    return enviados


def test_email_do_teste_encerrado_pede_assinatura():
    enviados = _expira_com_email("trial")

    assert len(enviados) == 1
    destino, assunto, corpo, html = enviados[0]
    assert destino == "fulano@exemplo.com"
    assert "teste" in assunto.lower()
    assert "https://x/checkout" in corpo
    assert "Assinar o VIP" in html


def test_email_do_vip_encerrado_pede_renovacao():
    enviados = _expira_com_email("vip")

    assert len(enviados) == 1
    assunto, html = enviados[0][1], enviados[0][3]
    assert "VIP" in assunto
    assert "Renovar o VIP" in html


def test_rodape_do_email_nao_diz_que_o_plano_esta_ativo():
    """A nota do rodapé era 'porque tem um plano ativo no Pick IA' · dizer isso
    a quem acabou de perder o acesso é o texto contradizendo o assunto."""
    from email_templates import NOTA_PLANO_ENCERRADO

    html = _expira_com_email("vip")[0][3]
    assert NOTA_PLANO_ENCERRADO in html
    assert "tem um plano ativo" not in html


def test_sem_injecao_de_email_manda_so_a_notificacao():
    """É o modo do staging: o noprod aponta pro banco de PRODUÇÃO, então um
    teste ali não pode mandar e-mail de verdade pro assinante real."""
    from plan_expiry import expirar_plano_vencido

    cur = _CurFake()
    assert expirar_plano_vencido(cur, _conta("vip", -1)) is True
    assert len(cur.notificacoes) == 1


def test_notificacao_ja_existente_nao_remanda_o_email():
    """create_notification faz upsert e sozinho não distingue 'criei agora' de
    'já existia'. Sem a checagem, uma corrida entre duas requisições da mesma
    conta (/auth/me roda ao montar e ao voltar pra aba) mandaria o mesmo
    e-mail duas vezes."""
    from plan_expiry import dedupe_vip_encerrado, expirar_plano_vencido

    enviados = []
    cur = _CurFake()
    user = _conta("vip", -1)
    cur.chaves.add(dedupe_vip_encerrado(user["expires_at"].date()))

    assert expirar_plano_vencido(cur, user,
                                 enviar_email=lambda *a: enviados.append(a),
                                 site_url="https://x") is True
    assert user["plan"] == "free", "o rebaixamento nao depende do aviso"
    assert enviados == []
    assert cur.notificacoes == []


# ── a fiação: backend e front ────────────────────────────────────────────────

def test_as_tres_rotas_usam_a_funcao_unica():
    """Login, refresh e /auth/me tinham três cópias do mesmo if. A terceira a
    ganhar responsabilidade nova seria a que ficaria pra trás em silêncio · e
    a que ficasse rebaixaria a conta sem nunca oferecer a assinatura."""
    import re
    from tests.test_home_2026_08 import _fonte

    fonte = _fonte("routers/auth.py")
    assert len(re.findall(r"expirar_plano_vencido\(cur, ", fonte)) == 3
    assert "UPDATE users SET plan='free', expires_at=NULL" not in fonte, \
        "voltou a rebaixar na mao em routers/auth.py"
    # E as tres passam o e-mail: sem isso o encerramento so' existe no sino.
    assert fonte.count("expirar_plano_vencido(cur, user, **_avisos_de_plano())") == 2
    assert "expirar_plano_vencido(cur, d, **_avisos_de_plano())" in fonte


def test_aviso_de_vencimento_alcanca_quem_nunca_desloga():
    """O cookie de sessao dura 30 dias e o uso e' mobile-first: o assinante
    mensal que deixa o app aberto atravessa o ciclo inteiro sem logar de novo,
    e ate' 23/08/2026 atravessava sem receber um unico e-mail de renovacao ·
    inclusive a faixa 0 ('expira hoje'). /auth/me e' a rota que toda visita
    chama, entao e' ela que fecha o buraco."""
    from tests.test_home_2026_08 import _fonte

    fonte = _fonte("routers/auth.py")
    assert fonte.count("avisar_plano_expirando(cur, ") == 2, \
        "o aviso de vencimento voltou a existir so' no login"


def test_popup_do_fim_do_acesso_esta_ligado_no_front():
    """O aviso precisa CHEGAR na tela, não só existir no banco.

    Três pontas, e cada uma sozinha é silenciosa se faltar: os tipos têm que
    existir no contexto (senão a notificação nunca vira `pendingAccessEnded`),
    o GlobalModals tem que renderizar o modal, e fechar tem que marcar como
    lida (senão ele reabre a cada visita e o "uma vez só" morre no front,
    mesmo com o servidor certo).
    """
    from tests.test_home_2026_08 import _front

    ctx = _front("context/NotificationContext.tsx")
    assert "'trial_ended'" in ctx, "tipo novo nao entrou na uniao do contexto"
    assert "'vip_ended'" in ctx, "VIP encerrado nao vira popup no front"
    assert "pendingAccessEnded" in ctx

    modais = _front("components/GlobalModals.tsx")
    assert "AccessEndedModal" in modais
    assert "markRead" in modais, "fechar o modal nao marca a notificacao como lida"

    # Um modal por vez: o fechamento mensal pede AÇÃO (confirmar a banca) e tem
    # prioridade; este e' convite e espera a vez. Sem isso os dois abrem juntos,
    # um por cima do outro.
    assert "!monthlyCloseOpen" in modais


def test_modal_troca_o_verbo_conforme_o_plano_que_acabou():
    """Um componente para os dois finais, mas nao um texto so': o popup do VIP
    dizendo 'Assinar' seria pedir assinatura a quem ja assinou."""
    from tests.test_home_2026_08 import _front

    modal = _front("components/AccessEndedModal.tsx")
    assert "Assinar o VIP" in modal and "Renovar o VIP" in modal
    assert "vip_ended" in _front("components/GlobalModals.tsx")


def test_icone_do_sino_cobre_os_dois_finais():
    """Tipo sem ícone cai no padrão (certo/errado de pick), e o item do sino
    passaria a dizer 'green' visualmente pra um aviso de plano."""
    from tests.test_home_2026_08 import _front

    sino = _front("components/NotificationBell.tsx")
    assert "n.type === 'trial_ended'" in sino
    assert "n.type === 'vip_ended'" in sino
