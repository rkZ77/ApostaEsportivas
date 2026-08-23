"""Onboarding interativo · o estado do tour mora na conta (21/08/2026).

O tour abre sozinho UMA vez, no primeiro acesso depois do cadastro, e nunca
mais. Sao 7 passos, ou 8 quando a conta ainda tem os 2 dias de VIP esperando a
confirmacao do e-mail -- por isso o backend valida o TETO, nao um numero fixo. A pergunta "esta pessoa já viu?" é da conta e não do
navegador, então quem responde é `users.tutorial_status` · com localStorage,
sair e entrar de novo, trocar de aparelho ou abrir numa aba anônima devolviam o
tour para quem já tinha passado por ele.

Os testes cobrem as três coisas que, quebradas, aparecem direto na cara do
usuário:

1. Conta antiga não pode receber o tour. É o backfill da migration, e ele só
   pode rodar UMA vez · solto, ele reapagaria o progresso de quem está no meio
   do tour a cada deploy.
2. A leitura tem que falhar para 'completed'. Se as colunas ainda não
   existirem no banco (já aconteceu aqui: coluna nova que só nasce na migration
   de startup), responder 'pending' abriria o tour na base inteira.
3. Pular e concluir têm que valer igual para "não abre mais", e o carimbo de
   quando terminou não pode ser reescrito por quem reabre o tour pelo menu.
"""

import re

import pytest

from routers import personal
from routers.personal import (
    TOURS,
    TUTORIAL_STATUS,
    TUTORIAL_TOTAL_STEPS,
    VIP_TOUR_TOTAL_STEPS,
    TutorialBody,
    _tutorial_payload,
    get_tutorial,
    save_tutorial,
)


# ───────────────────────────── dublês ──────────────────────────────────


class CursorFalso:
    """Cursor mínimo: guarda o SQL executado e devolve a linha combinada."""

    def __init__(self, linha=None, estoura=False):
        self._linha = linha
        self._estoura = estoura
        self.executados = []

    def execute(self, sql, params=None):
        if self._estoura:
            raise RuntimeError('column "tutorial_status" does not exist')
        self.executados.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self._linha

    def close(self):
        pass


class ConexaoFalsa:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


@pytest.fixture
def usuario():
    return {"id": 7, "sub": "7"}


def _liga(monkeypatch, cursor):
    conn = ConexaoFalsa(cursor)
    monkeypatch.setattr(personal, "get_connection", lambda: conn)
    return conn


# ──────────────────── o backfill da migration ──────────────────────────


def _fonte_da_migration():
    import pathlib

    caminho = pathlib.Path(__file__).resolve().parent.parent / "migrations.py"
    return caminho.read_text(encoding="utf-8")


def test_coluna_nasce_pendente_para_quem_ainda_nao_existe():
    """Conta nova tem que cair em 'pending', senão ninguém vê o tour."""
    fonte = _fonte_da_migration()
    assert "tutorial_status VARCHAR(12) NOT NULL DEFAULT 'pending'" in fonte


def test_backfill_marca_a_base_antiga_como_concluida():
    """Quem já tem conta não recebe o tour na cara no próximo login."""
    fonte = _fonte_da_migration()
    assert "UPDATE users SET tutorial_status = 'completed'" in fonte


def test_backfill_roda_dentro_do_if_e_nao_solto():
    """O UPDATE tem que estar preso ao nascimento da coluna.

    Solto ao lado de um ADD COLUMN IF NOT EXISTS, ele rodaria a cada startup e
    apagaria o progresso de todo mundo que estivesse no meio do tour · e ainda
    marcaria como concluído quem nunca viu.
    """
    fonte = _fonte_da_migration()
    bloco = re.search(
        r"IF NOT EXISTS \(\s*SELECT 1 FROM pg_attribute.*?END \$\$;",
        fonte,
        re.S,
    )
    assert bloco, "o bloco DO $$ do tutorial sumiu da migration"
    assert "UPDATE users SET tutorial_status = 'completed'" in bloco.group(0)

    # E não pode existir uma segunda cópia do UPDATE fora do bloco.
    assert fonte.count("UPDATE users SET tutorial_status = 'completed'") == 1


def test_passo_salvo_tem_coluna_propria():
    """Sem ele, recarregar a página no meio do tour volta para o 'Bem-vindo'."""
    fonte = _fonte_da_migration()
    assert "tutorial_step SMALLINT NOT NULL DEFAULT 0" in fonte


# ─────────────────────────── a leitura ─────────────────────────────────


def test_conta_nova_deve_abrir_o_tour(monkeypatch, usuario):
    _liga(monkeypatch, CursorFalso({"status": "pending", "step": 0}))
    r = get_tutorial(current_user=usuario)
    assert r["should_start"] is True
    assert r["step"] == 0
    assert r["total_steps"] == TUTORIAL_TOTAL_STEPS


@pytest.mark.parametrize("estado", ["completed", "skipped"])
def test_quem_concluiu_ou_pulou_nao_ve_de_novo(monkeypatch, usuario, estado):
    """Pular e concluir valem igual: o tour não volta sozinho nos dois casos."""
    _liga(monkeypatch, CursorFalso({"status": estado, "step": 4}))
    r = get_tutorial(current_user=usuario)
    assert r["should_start"] is False
    assert r["status"] == estado


def test_retoma_do_passo_em_que_parou(monkeypatch, usuario):
    """Recarregar a página, ou abrir no celular, continua de onde parou."""
    _liga(monkeypatch, CursorFalso({"status": "pending", "step": 3}))
    assert get_tutorial(current_user=usuario)["step"] == 3


def test_passo_fora_da_faixa_nao_estoura_a_tela(monkeypatch, usuario):
    """Roteiro encurtado depois de alguém parar no passo 9 não pode virar tela branca."""
    _liga(monkeypatch, CursorFalso({"status": "pending", "step": 99}))
    assert get_tutorial(current_user=usuario)["step"] == TUTORIAL_TOTAL_STEPS - 1


def test_coluna_ausente_no_banco_nao_abre_o_tour(monkeypatch, usuario):
    """A migration de startup pode não ter rodado ainda · falhar para 'completed'.

    Este é o caso real: coluna nova que só nasce no startup do servidor, e um
    deploy que sobe antes dela existir. 'pending' aqui significaria o tour
    abrindo para toda a base de uma vez.
    """
    _liga(monkeypatch, CursorFalso(estoura=True))
    r = get_tutorial(current_user=usuario)
    assert r["should_start"] is False
    assert r["status"] == "completed"


def test_estado_estranho_no_banco_nao_abre_o_tour(monkeypatch, usuario):
    _liga(monkeypatch, CursorFalso({"status": "seila", "step": 0}))
    assert get_tutorial(current_user=usuario)["should_start"] is False


# ─────────────────────────── a gravação ────────────────────────────────


def test_avancar_passo_nao_tira_a_conta_de_pendente(monkeypatch, usuario):
    """Guardar onde parou é diferente de concluir."""
    cur = CursorFalso({"status": "pending", "step": 2})
    _liga(monkeypatch, cur)
    r = save_tutorial(TutorialBody(step=2), current_user=usuario)
    assert r["should_start"] is True

    sql, params = cur.executados[0]
    assert "tutorial_step = %s" in sql
    # `tutorial_status` ainda aparece no RETURNING · o que não pode é ele
    # entrar no SET e apagar o 'pending' de quem só andou um passo.
    assert "tutorial_status = %s" not in sql
    assert "tutorial_finished_at" not in sql
    assert params == (2, 7)


@pytest.mark.parametrize("estado", ["completed", "skipped"])
def test_concluir_e_pular_carimbam_a_data(monkeypatch, usuario, estado):
    cur = CursorFalso({"status": estado, "step": 6})
    _liga(monkeypatch, cur)
    save_tutorial(TutorialBody(status=estado), current_user=usuario)

    sql, _ = cur.executados[0]
    assert "tutorial_status = %s" in sql
    assert "tutorial_finished_at = COALESCE(tutorial_finished_at, NOW())" in sql


def test_reabrir_pelo_menu_nao_reescreve_a_data_do_fim(monkeypatch, usuario):
    """COALESCE, e não NOW() direto.

    Quem reabre o tour por "Ver tutorial" e conclui de novo mandaria um segundo
    'completed'. A data em que a pessoa aprendeu a usar o site é a primeira.
    """
    cur = CursorFalso({"status": "completed", "step": 6})
    _liga(monkeypatch, cur)
    save_tutorial(TutorialBody(status="completed"), current_user=usuario)

    sql, _ = cur.executados[0]
    assert "tutorial_finished_at = NOW()" not in sql
    assert "COALESCE(tutorial_finished_at, NOW())" in sql


def test_estado_invalido_e_recusado(usuario):
    with pytest.raises(Exception) as e:
        save_tutorial(TutorialBody(status="qualquer"), current_user=usuario)
    assert e.value.status_code == 400


def test_corpo_vazio_e_recusado(usuario):
    """Sem isto, o UPDATE sairia com a lista de campos vazia e SQL inválido."""
    with pytest.raises(Exception) as e:
        save_tutorial(TutorialBody(), current_user=usuario)
    assert e.value.status_code == 400


def test_passo_acima_do_roteiro_e_recusado_na_entrada():
    """A validação é do Pydantic · o teto vem de TUTORIAL_TOTAL_STEPS."""
    with pytest.raises(Exception):
        TutorialBody(step=TUTORIAL_TOTAL_STEPS + 1)


def test_passo_negativo_e_recusado():
    with pytest.raises(Exception):
        TutorialBody(step=-1)


def test_passo_no_limite_e_guardado_dentro_da_faixa(monkeypatch, usuario):
    """O front manda o índice seguinte ao fechar o último passo."""
    cur = CursorFalso({"status": "pending", "step": TUTORIAL_TOTAL_STEPS - 1})
    _liga(monkeypatch, cur)
    save_tutorial(TutorialBody(step=TUTORIAL_TOTAL_STEPS), current_user=usuario)

    _, params = cur.executados[0]
    assert params[0] == TUTORIAL_TOTAL_STEPS - 1


def test_falha_de_escrita_faz_rollback(monkeypatch, usuario):
    cur = CursorFalso(estoura=True)
    conn = _liga(monkeypatch, cur)
    with pytest.raises(Exception) as e:
        save_tutorial(TutorialBody(status="completed"), current_user=usuario)
    assert e.value.status_code == 500
    assert conn.rollbacks == 1


# ─────────────────────── contrato com a tela ───────────────────────────


def test_o_front_e_o_back_contam_os_mesmos_passos():
    """O teto do PUT e o maior roteiro possivel tem que ser o mesmo numero.

    O tour tem 7 passos fixos mais o de confirmar e-mail, que so' entra pra quem
    ainda tem trial na mesa. Se o backend validar 7 e a tela mandar o indice 7
    (oitavo passo), o PUT volta 422 e a posicao para de ser salva no meio do
    tour, sem erro visivel na tela.
    """
    import pathlib

    constantes = (
        pathlib.Path(__file__).resolve().parents[2]
        / "frontend" / "src" / "components" / "onboarding" / "constantes.ts"
    ).read_text(encoding="utf-8")
    assert f"MAX_PASSOS = {TUTORIAL_TOTAL_STEPS}" in constantes
    # E o piso: os passos que TODA conta ve.
    assert "PASSOS_FIXOS = 7" in constantes


def test_o_passo_do_email_so_entra_pra_quem_tem_trial_esperando():
    """O 8o passo e' condicional, e a condicao mora num lugar so.

    Ele oferece os 2 dias de VIP em troca de confirmar o e-mail. Pra quem ja
    confirmou, ou ja gastou o trial, seria uma tela pedindo uma coisa que nao
    muda nada. `passoDoEmailEntra` e' usado pelo roteiro (pra montar a lista) e
    pelo provider (pra contar) -- duas copias dessa condicao divergem no
    primeiro ajuste.
    """
    import pathlib

    constantes = (
        pathlib.Path(__file__).resolve().parents[2]
        / "frontend" / "src" / "components" / "onboarding" / "constantes.ts"
    ).read_text(encoding="utf-8")
    assert "export function passoDoEmailEntra" in constantes
    assert "ctx.emailPendente && ctx.trialNaMesa" in constantes
    assert "PASSOS_FIXOS + (passoDoEmailEntra(ctx) ? 1 : 0)" in constantes


def test_estados_possiveis_sao_so_esses_tres():
    assert set(TUTORIAL_STATUS) == {"pending", "completed", "skipped"}


def test_payload_traz_tudo_que_a_tela_precisa():
    r = _tutorial_payload("pending", 2, TUTORIAL_TOTAL_STEPS, "boas-vindas")
    assert set(r) == {"tour", "status", "step", "total_steps", "should_start"}


# ───────────────────── o roteiro do VIP ────────────────────────────────


def test_os_dois_roteiros_existem_e_apontam_pra_colunas_diferentes():
    """Um estado por roteiro. Compartilhando coluna, concluir um fecharia o outro."""
    assert set(TOURS) == {"boas-vindas", "vip"}
    colunas = [c["status"] for c in TOURS.values()]
    assert len(set(colunas)) == 2, "os dois roteiros nao podem dividir a mesma coluna"
    assert TOURS["vip"]["total"] == VIP_TOUR_TOTAL_STEPS


def test_tour_desconhecido_e_recusado(usuario):
    """O nome do tour vira NOME DE COLUNA no SQL. Recusar o que nao esta no
    dicionario e' o que impede a query string de escolher coluna."""
    with pytest.raises(Exception) as e:
        get_tutorial(tour="'; DROP TABLE users; --", current_user=usuario)
    assert e.value.status_code == 400


def test_vip_pendente_abre_o_tour_do_vip(monkeypatch, usuario):
    cur = CursorFalso({"status": "pending", "step": 0})
    _liga(monkeypatch, cur)
    r = get_tutorial(tour="vip", current_user=usuario)
    assert r["should_start"] is True
    assert r["tour"] == "vip"
    assert r["total_steps"] == VIP_TOUR_TOTAL_STEPS

    sql, _ = cur.executados[0]
    assert "vip_tour_status" in sql and "vip_tour_step" in sql
    assert "tutorial_status" not in sql, "o roteiro do VIP nao pode ler a coluna do outro"


def test_vip_grava_na_coluna_do_vip(monkeypatch, usuario):
    cur = CursorFalso({"status": "completed", "step": 4})
    _liga(monkeypatch, cur)
    save_tutorial(TutorialBody(status="completed"), tour="vip", current_user=usuario)

    sql, _ = cur.executados[0]
    assert "vip_tour_status = %s" in sql
    assert "vip_tour_finished_at = COALESCE(vip_tour_finished_at, NOW())" in sql
    assert "tutorial_status" not in sql


def test_passo_do_vip_e_limitado_ao_roteiro_do_vip(monkeypatch, usuario):
    """O teto do PUT e' o maior entre os roteiros; o clamp por roteiro vem
    depois. Sem ele, o passo 7 (valido no de boas-vindas) entraria no do VIP,
    que tem 5, e a tela abriria num passo que nao existe."""
    cur = CursorFalso({"status": "pending", "step": VIP_TOUR_TOTAL_STEPS - 1})
    _liga(monkeypatch, cur)
    save_tutorial(TutorialBody(step=7), tour="vip", current_user=usuario)

    _, params = cur.executados[0]
    assert params[0] == VIP_TOUR_TOTAL_STEPS - 1


def test_backfill_do_vip_poupa_so_quem_ja_e_assinante():
    """A diferenca em relacao ao outro backfill e' o ponto do recurso.

    La todo mundo virou 'completed'. Aqui free e trial precisam ficar
    'pending', porque e' isso que faz o tour aparecer no dia em que eles
    assinarem. Marcar a base inteira entregaria a assinatura sem nenhuma tela
    dizendo o que mudou.
    """
    fonte = _fonte_da_migration()
    assert "vip_tour_status VARCHAR(12) NOT NULL DEFAULT 'pending'" in fonte
    assert (
        "UPDATE users SET vip_tour_status = 'completed' WHERE plan IN ('vip', 'admin')"
        in fonte
    )
    # E preso ao nascimento da coluna, como o outro.
    bloco = re.search(
        r"AND attname  = 'vip_tour_status'.*?END \$\$;", fonte, re.S,
    )
    assert bloco and "UPDATE users SET vip_tour_status" in bloco.group(0)


def test_o_front_e_o_back_contam_os_mesmos_passos_do_vip():
    import pathlib

    constantes = (
        pathlib.Path(__file__).resolve().parents[2]
        / "frontend" / "src" / "components" / "onboarding" / "constantes.ts"
    ).read_text(encoding="utf-8")
    assert f"TOTAL_PASSOS_VIP = {VIP_TOUR_TOTAL_STEPS}" in constantes
    # E os nomes dos roteiros tem que bater dos dois lados.
    for nome in TOURS:
        assert f"'{nome}'" in constantes, f"o front nao conhece o roteiro {nome}"
