"""Disparos de reengajamento e aviso no WhatsApp.

Nada aqui toca banco. O que se verifica sao as TRAVAS, que e onde este recurso
pode fazer estrago de verdade:

  * e-mail de marketing sem porta de saida vira reclamacao de spam, e
    reclamacao de spam derruba a entrega dos transacionais junto;
  * disparo sem dedupe manda a mesma mensagem duas vezes, e a segunda e a que
    faz a pessoa bloquear;
  * aviso de WhatsApp sem opt-in e sem telefone verificado e o caminho mais
    curto pro numero comprado ser banido pela Meta;
  * o staging aponta pro banco de PRODUCAO, entao envio em lote de la
    alcancaria a base real.
"""

import os
import re

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRONT = os.path.join(os.path.dirname(_BACKEND), "frontend", "src")


def _back(caminho: str) -> str:
    with open(os.path.join(_BACKEND, caminho), encoding="utf-8") as f:
        return f.read()


def _front(caminho: str) -> str:
    with open(os.path.join(_FRONT, caminho), encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------ o catalogo

def test_catalogo_tem_id_unico():
    import campanhas

    ids = [c.id for c in campanhas.CAMPANHAS]
    assert len(ids) == len(set(ids)), ids


@pytest.mark.parametrize("cid", [
    "novidades", "nunca_entrou", "trial_expirado", "vip_vencido", "sem_seguir_pick",
])
def test_toda_campanha_e_recuperavel_por_id(cid):
    import campanhas

    assert campanhas.campanha(cid).id == cid


def test_campanha_desconhecida_levanta():
    import campanhas

    with pytest.raises(KeyError):
        campanhas.campanha("promocao_relampago")


def test_todo_texto_de_whatsapp_tem_nome_e_link():
    """Sem `{url}` a mensagem vira propaganda sem destino, e e' justamente o
    tipo que faz a pessoa denunciar em vez de clicar."""
    import campanhas

    for c in campanhas.CAMPANHAS:
        assert "{nome}" in c.whatsapp, c.id
        assert "{url}" in c.whatsapp, c.id


def test_nenhum_texto_de_tela_tem_emoji_travessao_ou_ponto_do_meio():
    """Vale pro que a PESSOA le: assunto, titulo, paragrafo e WhatsApp. O
    `objetivo` fica de fora porque ele so' aparece pro admin."""
    import campanhas

    textos = []
    for c in campanhas.CAMPANHAS:
        textos += [c.assunto, c.titulo, c.whatsapp, *c.paragrafos]
    textos += [p for item in campanhas.NOVIDADES for p in item]
    for t in textos:
        assert "—" not in t, t
        assert "·" not in t, t
        assert not re.search(r"[\U0001F300-\U0001FAFF✀-➿]", t), t


# --------------------------------------------------- o SQL do publico

@pytest.mark.parametrize("cid", [c for c in (
    "novidades", "nunca_entrou", "trial_expirado", "vip_vencido", "sem_seguir_pick")])
def test_publico_de_email_respeita_o_descadastro(cid):
    """A checagem mora no SQL, nao no Python: filtrar depois faria a contagem
    da tela prometer envios que a fila nao cumpre."""
    import campanhas

    sql = campanhas.sql_publico(campanhas.campanha(cid), "email")
    assert "email_marketing_opt_out" in sql
    assert "u.deleted_at IS NULL" in sql
    assert "u.plan <> 'admin'" in sql


@pytest.mark.parametrize("cid", ["novidades", "nunca_entrou"])
def test_publico_de_whatsapp_exige_telefone_verificado(cid):
    import campanhas

    sql = campanhas.sql_publico(campanhas.campanha(cid), "whatsapp")
    assert "phone_verified" in sql


def test_publico_exclui_quem_ja_recebeu_e_respeita_a_janela():
    import campanhas

    sql = campanhas.sql_publico(campanhas.campanha("novidades"), "email")
    assert sql.count("NOT EXISTS") >= 2
    assert f"INTERVAL '{campanhas.JANELA_ENTRE_ENVIOS_DIAS} days'" in sql


def test_publico_e_a_mesma_consulta_nos_dois_usos():
    """A contagem da tela e a fila do envio saem da MESMA funcao · duas
    consultas parecidas e como o painel comeca a prometer 300 e a fila sair
    com 180."""
    admin = _back(os.path.join("routers", "admin.py"))
    assert admin.count("campanhas.sql_publico(") >= 4


# ------------------------------------------------------- descadastro

def test_token_de_descadastro_fecha_o_circulo(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "segredo-de-teste")
    import campanhas

    token = campanhas.token_descadastro(42)
    assert campanhas.user_de_token(token) == 42


@pytest.mark.parametrize("ruim", [
    "", "42", "42.", "42.abc", "abc.def", None, "43.{assinatura_do_42}",
])
def test_token_adulterado_nao_descadastra_ninguem(monkeypatch, ruim):
    monkeypatch.setenv("JWT_SECRET", "segredo-de-teste")
    import campanhas

    if ruim == "43.{assinatura_do_42}":
        ruim = "43." + campanhas.token_descadastro(42).split(".", 1)[1]
    assert campanhas.user_de_token(ruim) is None


def test_descadastro_e_rota_publica_sem_login():
    """Quem sumiu nao vai logar pra desligar propaganda · vai marcar como spam,
    e spam derruba a entrega do transacional junto."""
    public = _back(os.path.join("routers", "public.py"))
    assert '@router.get("/descadastrar")' in public
    assert "get_current_user" not in public.split("Descadastro de e-mail")[1]


def test_descadastro_nao_desativa_a_conta():
    public = _back(os.path.join("routers", "public.py"))
    trecho = public.split("def descadastrar_email")[1]
    assert "email_marketing_opt_out = TRUE" in trecho
    assert "active = FALSE" not in trecho


def test_email_de_campanha_leva_o_link_de_descadastro():
    from email_templates import campanha_html

    html = campanha_html(
        "Rafael", "Titulo", ["Corpo"], "https://x/picks", "Ver",
        "https://x/api/public/descadastrar?token=1.abc",
    )
    assert "descadastrar?token=1.abc" in html
    assert "Nao quero mais receber" in html


def test_numeros_somem_quando_nao_ha_pick_liquidado():
    """Mes sem pick resolvido existe (o motor corta volume de proposito). Um
    "0% de acerto" num e-mail de reengajamento diz o contrario do que o dado
    diz, entao o bloco nao aparece."""
    from email_templates import campanha_html

    html = campanha_html("Rafael", "T", ["C"], "u", "V", "d", numeros={"total": 0})
    assert "de acerto" not in html


def test_numeros_aparecem_quando_ha_dado():
    from email_templates import campanha_html

    html = campanha_html("Rafael", "T", ["C"], "u", "V", "d",
                         numeros={"total": 120, "win_rate": 64.2, "lucro": 18.3})
    assert "64.2%" in html and "120" in html


# ------------------------------------------------------------- disparo

def test_envio_em_lote_exige_side_effects():
    """O noprod aponta pro banco de PRODUCAO: sem este freio, um clique no
    staging manda e-mail real E grava o dedupe, e o disparo de verdade deixa
    essa gente de fora depois."""
    admin = _back(os.path.join("routers", "admin.py"))
    trecho = admin.split("def admin_disparo_enviar")[1]
    assert "side_effects_enabled()" in trecho
    assert "409" in trecho


def test_teste_nao_grava_dedupe():
    admin = _back(os.path.join("routers", "admin.py"))
    trecho = admin.split("def admin_disparo_enviar")[1].split("if not side_effects_enabled")[0]
    assert "INSERT INTO campanha_envios" not in trecho


def test_o_registro_vem_antes_do_envio():
    """Se a requisicao cair no meio, o pior caso tem que ser "e-mail que nao
    saiu", nunca "mesmo e-mail duas vezes"."""
    admin = _back(os.path.join("routers", "admin.py"))
    trecho = admin.split("fila = [dict(r) for r in cur.fetchall()]")[1]
    assert trecho.index("INSERT INTO campanha_envios") < trecho.index("_send_email(to=d")


def test_disparo_tem_teto_por_clique():
    admin = _back(os.path.join("routers", "admin.py"))
    assert "_DISPARO_LIMITE_MAX" in admin
    assert "limite tem que ficar entre" in admin


def test_whatsapp_de_campanha_nao_dispara_sozinho():
    """A ausencia do botao E a decisao · a politica da Meta pra vertical de
    aposta trata denuncia no nivel da CONTA, e o numero e um so."""
    admin = _back(os.path.join("routers", "admin.py"))
    trecho = admin.split("def admin_disparo_whatsapp")[1].split("@router")[0]
    assert "enviar_template" not in trecho
    assert "wa.me" in trecho or "link_whatsapp" in trecho


# ------------------------------------------- aviso ao vivo no WhatsApp

def _destinos_sql() -> str:
    notif = _back(os.path.join("routers", "notifications.py"))
    return notif.split("def _destinos_whatsapp")[1].split("def _disparar_whatsapp")[0]


def test_nenhum_aviso_sai_sem_opt_in_e_telefone_verificado():
    """A consulta e uma so' pros tres avisos de proposito: escrita a mao em
    cada lugar, uma copia esqueceria o opt-in e mandaria mensagem pra quem nao
    pediu, sem dar erro nenhum."""
    trecho = _destinos_sql()
    assert "whatsapp_opt_in" in trecho
    assert "phone_verified" in trecho
    assert "u.deleted_at IS NULL" in trecho


@pytest.mark.parametrize("tipo,coluna", [
    ("ao_vivo", "whatsapp_ao_vivo"),
    ("picks_do_dia", "whatsapp_picks_do_dia"),
    ("resultado", "whatsapp_resultado"),
])
def test_cada_aviso_tem_a_propria_preferencia(tipo, coluna):
    """Desligar um aviso nao pode desligar os outros dois."""
    import sys

    sys.path.insert(0, _BACKEND)
    from routers import notifications as n

    assert n._AVISOS_WA[tipo][0] == coluna


def test_aviso_ao_vivo_e_so_de_quem_tem_o_pro():
    """O corpo carrega mercado, linha e odd · e a analise que a aba cobra.
    Os outros dois nao levam pick nenhum, entao nao tem gate de plano."""
    notif = _back(os.path.join("routers", "notifications.py"))
    assert "gate=SQL_PRO_ATIVO" in notif.split("def avisar_ao_vivo_no_whatsapp")[1]
    for fn in ("def avisar_picks_do_dia_no_whatsapp", "def avisar_resultado_no_whatsapp"):
        assert "SQL_PRO_ATIVO" not in notif.split(fn)[1].split("def ")[0]


def test_disparo_tem_teto_diario_e_dedupe():
    notif = _back(os.path.join("routers", "notifications.py"))
    assert "TETO_WHATSAPP_AO_VIVO_DIA" in notif
    trecho = notif.split("def _disparar_whatsapp")[1]
    assert "ON CONFLICT (user_id, dedupe_key) DO NOTHING" in trecho
    assert "DATE_TRUNC('day', NOW())" in _destinos_sql()


def test_nenhum_aviso_sai_do_staging():
    notif = _back(os.path.join("routers", "notifications.py"))
    trecho = notif.split("def _disparar_whatsapp")[1]
    assert "side_effects_enabled()" in trecho
    assert "whatsapp_configurado()" in trecho


def test_registro_vem_antes_do_envio_no_whatsapp():
    notif = _back(os.path.join("routers", "notifications.py"))
    trecho = notif.split("def _disparar_whatsapp")[1]
    assert trecho.index("INSERT INTO whatsapp_envios") < trecho.index("wa.enviar_template")


def test_anulada_nao_vira_mensagem():
    """A regua do canal e "se nao muda uma decisao sua, nao e enviada", e PUSH
    e' exatamente o caso: ninguem ganhou nem perdeu. Fica so' no sino."""
    notif = _back(os.path.join("routers", "notifications.py"))
    trecho = notif.split("def avisar_resultado_no_whatsapp")[1]
    assert 'if rotulo == "PUSH":' in trecho
    assert trecho.split('if rotulo == "PUSH":')[1].lstrip().startswith("return 0")


def test_green_e_red_sao_templates_separados():
    """Decisao do README: o marcador vira texto fixo em vez de variavel, e o
    red pode ter tom sobrio em vez da frase comemorativa do green."""
    import whatsapp as wa

    assert wa.TEMPLATE_RESULTADO_GREEN != wa.TEMPLATE_RESULTADO_RED
    notif = _back(os.path.join("routers", "notifications.py"))
    trecho = notif.split("def avisar_resultado_no_whatsapp")[1]
    assert "HALF-WIN" in trecho


def test_picks_do_dia_e_resultado_estao_ligados_de_verdade():
    """Toggle no perfil que nao dispara nada e pior do que toggle nenhum."""
    admin = _back(os.path.join("routers", "admin.py"))
    assert "avisar_picks_do_dia_no_whatsapp" in admin
    notif = _back(os.path.join("routers", "notifications.py"))
    assert "avisar_resultado_no_whatsapp(" in notif.split("def notify_pick_result")[1]


def test_sino_vem_antes_do_whatsapp():
    """O item do sino e a fonte da verdade e nao pode depender de a Meta
    responder."""
    notif = _back(os.path.join("routers", "notifications.py"))
    trecho = notif.split("def notificar_pick_live_novo")[1]
    assert trecho.index("notify_pro_users") < trecho.index("avisar_ao_vivo_no_whatsapp")


def test_whatsapp_em_modo_log_nao_conta_como_configurado(monkeypatch):
    """Mesmo desenho do `sms_configurado`: tratar o modo de desenvolvimento
    como disponivel faria o /admin dizer que 300 avisos sairam."""
    monkeypatch.delenv("WHATSAPP_PROVIDER", raising=False)
    import whatsapp as wa

    assert wa.whatsapp_configurado() is False


def test_whatsapp_cloud_sem_token_tambem_nao_conta(monkeypatch):
    monkeypatch.setenv("WHATSAPP_PROVIDER", "cloud")
    monkeypatch.delenv("WHATSAPP_TOKEN", raising=False)
    monkeypatch.delenv("WHATSAPP_PHONE_ID", raising=False)
    import whatsapp as wa

    assert wa.whatsapp_configurado() is False


def test_modo_log_nao_fala_com_a_meta(monkeypatch):
    monkeypatch.delenv("WHATSAPP_PROVIDER", raising=False)
    import whatsapp as wa

    def _explode(*_a, **_kw):
        raise AssertionError("modo log nao pode abrir conexao")

    monkeypatch.setattr(wa.httpx, "post", _explode)
    wa.enviar_template("+5511999998888", wa.TEMPLATE_AO_VIVO, ["a", "b", "c", "d"])
    wa.enviar_texto("+5511999998888", "oi")


@pytest.mark.parametrize("entrada,esperado", [
    ("+5511999998888", "5511999998888"),
    ("11999998888",    "5511999998888"),
    ("(11) 99999-8888", "5511999998888"),
])
def test_telefone_vira_e164(entrada, esperado):
    import whatsapp as wa

    assert wa._e164(entrada) == esperado


# ------------------------------------------------------------ migration

@pytest.mark.parametrize("coluna", [
    "email_marketing_opt_out", "whatsapp_ao_vivo",
    "whatsapp_picks_do_dia", "whatsapp_resultado",
])
def test_colunas_de_preferencia_existem_na_migration(coluna):
    assert coluna in _back("migrations.py")


def test_dedupe_de_campanha_e_indice_unico():
    """Sem o indice, dois cliques no botao mandam o mesmo e-mail duas vezes."""
    m = _back("migrations.py")
    assert "idx_campanha_envios_unico" in m
    assert "ON campanha_envios (campanha, canal, user_id)" in m


def test_aviso_automatico_tem_tabela_propria():
    """Junto com campanha_envios, a janela de 14 dias entre campanhas engoliria
    o aviso de pick ao vivo que a pessoa pediu pra receber."""
    m = _back("migrations.py")
    assert "CREATE TABLE IF NOT EXISTS whatsapp_envios" in m
    assert "idx_whatsapp_envios_unico" in m


# -------------------------------------------------------------- as telas

def test_admin_tem_a_aba_disparos():
    admin = _front("pages/Admin.tsx")
    assert "{ key: 'disparos'" in admin
    assert "AdminDisparos" in admin


def test_tela_mostra_o_publico_antes_do_botao():
    """Disparo manda e-mail de verdade · um clique no escuro nao pode ser a
    forma de descobrir pra quantas pessoas ele foi."""
    tela = _front("components/AdminDisparos.tsx")
    assert "previa" in tela
    assert tela.index("publico_email") < tela.index("Disparar")


def test_tela_de_whatsapp_nao_tem_botao_de_lote():
    tela = _front("components/AdminDisparos.tsx")
    trecho = tela.split("canal === 'whatsapp'")[-1]
    assert "Mandei" in trecho
    assert "Disparar" not in trecho


def test_perfil_tem_o_interruptor_de_whatsapp():
    perfil = _front("pages/Profile.tsx")
    assert "AvisosWhatsApp" in perfil


def test_interruptor_some_sem_provedor():
    """Toggle que aceita o clique e nao entrega aviso nenhum e pior do que nao
    existir · mesmo raciocinio do card de Telefone com `sms_disponivel`."""
    card = _front("components/AvisosWhatsApp.tsx")
    assert "!p.disponivel) return null" in card


def test_interruptor_exige_telefone_verificado():
    card = _front("components/AvisosWhatsApp.tsx")
    assert "phone_verified" in card
    back = _back(os.path.join("routers", "notifications.py"))
    trecho = back.split("def put_prefs_whatsapp")[1]
    assert "Confirme seu telefone" in trecho
