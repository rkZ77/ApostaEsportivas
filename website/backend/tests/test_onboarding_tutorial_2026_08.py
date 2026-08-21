"""Onboarding interativo · o estado do tour mora na conta (21/08/2026).

O tour de sete passos abre sozinho UMA vez, no primeiro acesso depois do
cadastro, e nunca mais. A pergunta "esta pessoa já viu?" é da conta e não do
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
    TUTORIAL_STATUS,
    TUTORIAL_TOTAL_STEPS,
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
    _liga(monkeypatch, CursorFalso({"tutorial_status": "pending", "tutorial_step": 0}))
    r = get_tutorial(current_user=usuario)
    assert r["should_start"] is True
    assert r["step"] == 0
    assert r["total_steps"] == TUTORIAL_TOTAL_STEPS


@pytest.mark.parametrize("estado", ["completed", "skipped"])
def test_quem_concluiu_ou_pulou_nao_ve_de_novo(monkeypatch, usuario, estado):
    """Pular e concluir valem igual: o tour não volta sozinho nos dois casos."""
    _liga(monkeypatch, CursorFalso({"tutorial_status": estado, "tutorial_step": 4}))
    r = get_tutorial(current_user=usuario)
    assert r["should_start"] is False
    assert r["status"] == estado


def test_retoma_do_passo_em_que_parou(monkeypatch, usuario):
    """Recarregar a página, ou abrir no celular, continua de onde parou."""
    _liga(monkeypatch, CursorFalso({"tutorial_status": "pending", "tutorial_step": 3}))
    assert get_tutorial(current_user=usuario)["step"] == 3


def test_passo_fora_da_faixa_nao_estoura_a_tela(monkeypatch, usuario):
    """Roteiro encurtado depois de alguém parar no passo 9 não pode virar tela branca."""
    _liga(monkeypatch, CursorFalso({"tutorial_status": "pending", "tutorial_step": 99}))
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
    _liga(monkeypatch, CursorFalso({"tutorial_status": "seila", "tutorial_step": 0}))
    assert get_tutorial(current_user=usuario)["should_start"] is False


# ─────────────────────────── a gravação ────────────────────────────────


def test_avancar_passo_nao_tira_a_conta_de_pendente(monkeypatch, usuario):
    """Guardar onde parou é diferente de concluir."""
    cur = CursorFalso({"tutorial_status": "pending", "tutorial_step": 2})
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
    cur = CursorFalso({"tutorial_status": estado, "tutorial_step": 6})
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
    cur = CursorFalso({"tutorial_status": "completed", "tutorial_step": 6})
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
    cur = CursorFalso({"tutorial_status": "pending", "tutorial_step": TUTORIAL_TOTAL_STEPS - 1})
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
    """O roteiro tem sete passos, e o teto do PUT sai daqui."""
    import pathlib

    constantes = (
        pathlib.Path(__file__).resolve().parents[2]
        / "frontend" / "src" / "components" / "onboarding" / "constantes.ts"
    ).read_text(encoding="utf-8")
    assert f"TOTAL_PASSOS = {TUTORIAL_TOTAL_STEPS}" in constantes


def test_estados_possiveis_sao_so_esses_tres():
    assert set(TUTORIAL_STATUS) == {"pending", "completed", "skipped"}


def test_payload_traz_tudo_que_a_tela_precisa():
    r = _tutorial_payload("pending", 2)
    assert set(r) == {"status", "step", "total_steps", "should_start"}
