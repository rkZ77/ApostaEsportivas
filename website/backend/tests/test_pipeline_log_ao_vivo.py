"""Log ao vivo do pipeline no /admin.

Ate 2026-08-13 o log so' existia DEPOIS: `proc.communicate()` espera o processo
inteiro terminar, e o que sobrava era o rabo de 1500 caracteres. Numa etapa de
30 minutos -- coleta de odds em dia cheio, ou o Stage 6 de historico por time --
a tela ficava com uma bolinha amarela e mais nada, sem dar pra distinguir
"progredindo" de "travado".

O que estes testes protegem, em ordem de importancia:

  1. o log NAO chega em quem nao e' admin (a saida crua carrega host de banco,
     traceback e contagem de requisicao de API);
  2. a leitura incremental nao repete nem pula linha quando o buffer gira;
  3. o buffer e' limitado, porque vive na memoria do processo web.

Nenhum teste sobe servidor nem roda subprocesso.
"""
import ast
import inspect
import os

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADMIN = os.path.join(BACKEND, "routers", "admin.py")


@pytest.fixture(scope="module")
def fonte():
    with open(ADMIN, encoding="utf-8") as fh:
        return fh.read()


# ── 1. Quem pode ver ──────────────────────────────────────────────────────
def test_log_exige_admin(fonte):
    """A saida crua dos scripts nao pode chegar em assinante. A tela de espera
    dele continua em /pipeline-status-public, que expoe so' o rotulo da etapa."""
    arvore = ast.parse(fonte)
    alvo = next(n for n in ast.walk(arvore)
                if isinstance(n, ast.FunctionDef) and n.name == "pipeline_log")
    defaults = [ast.unparse(d) for d in alvo.args.defaults]
    assert any("require_admin" in d for d in defaults), \
        "pipeline_log sem require_admin: log cru vazaria pra usuario comum"


def test_status_publico_nao_ganhou_log(fonte):
    """A rota que o assinante consulta continua sem `log`/`error`."""
    arvore = ast.parse(fonte)
    alvo = next(n for n in ast.walk(arvore)
                if isinstance(n, ast.FunctionDef) and n.name == "pipeline_status_public")
    corpo = ast.unparse(alvo)
    assert "_pipeline_logs" not in corpo


# ── 2. Leitura incremental ────────────────────────────────────────────────
def _buffer(**kw):
    import routers.admin as admin
    return admin._LogBuffer(**kw)


def test_le_so_o_que_chegou_depois():
    b = _buffer()
    for i in range(3):
        b.append(f"linha {i}")

    linhas, proximo = b.desde(0)
    assert linhas == ["linha 0", "linha 1", "linha 2"]
    assert proximo == 3

    b.append("linha 3")
    novas, proximo = b.desde(proximo)
    assert novas == ["linha 3"]
    assert proximo == 4


def test_nada_novo_devolve_vazio():
    b = _buffer()
    b.append("unica")
    _, proximo = b.desde(0)

    assert b.desde(proximo) == ([], 1)


def test_buffer_girado_nao_repete_linha_antiga():
    """O caso que um `deque` simples erraria: passando do limite, os indices
    escorregam e a tela receberia de novo o que ja mostrou."""
    b = _buffer(maximo=3)
    for i in range(3):
        b.append(f"L{i}")
    _, cursor = b.desde(0)

    for i in range(3, 6):
        b.append(f"L{i}")
    novas, cursor2 = b.desde(cursor)

    assert novas == ["L3", "L4", "L5"]
    assert cursor2 == 6


def test_cursor_atrasado_nao_estoura():
    """Aba aberta ha muito tempo pede `desde` de um ponto que ja saiu do
    buffer: tem que devolver o que sobrou, nao quebrar."""
    b = _buffer(maximo=2)
    for i in range(10):
        b.append(f"L{i}")

    linhas, proximo = b.desde(0)
    assert linhas == ["L8", "L9"]
    assert proximo == 10


# ── 3. Limite de memoria ──────────────────────────────────────────────────
def test_buffer_e_limitado():
    """Isto vive na memoria do processo que atende o site."""
    import routers.admin as admin

    b = _buffer()
    for i in range(admin._LOG_MAX_LINHAS * 3):
        b.append(f"L{i}")

    assert len(b.linhas) == admin._LOG_MAX_LINHAS


# ── 4. Ligacao com a execucao ─────────────────────────────────────────────
def test_saida_e_drenada_linha_a_linha_e_nao_no_fim(fonte):
    """A regressao original: communicate() espera o processo inteiro. Se
    alguem voltar a usa-lo pro fluxo normal, o log ao vivo morre em silencio."""
    arvore = ast.parse(fonte)
    alvo = next(n for n in ast.walk(arvore)
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_and_track")
    corpo = ast.unparse(alvo)
    assert "_drenar" in corpo
    assert "proc.communicate()" not in corpo


def test_subprocesso_roda_sem_buffer_de_saida(fonte):
    """Sem PYTHONUNBUFFERED o Python do subprocesso segura a saida em blocos de
    4KB quando nao ha terminal, e o log "ao vivo" chegaria de minutos em
    minutos -- quase o problema que ele veio resolver."""
    arvore = ast.parse(fonte)
    alvo = next(n for n in ast.walk(arvore)
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_and_track")
    assert "PYTHONUNBUFFERED" in ast.unparse(alvo)


def test_tudo_junta_as_etapas_num_log_so(fonte):
    """Quem clica em "Rodar tudo" quer uma fita corrida, nao nove separadas."""
    arvore = ast.parse(fonte)
    alvo = next(n for n in ast.walk(arvore)
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_tudo")
    corpo = ast.unparse(alvo)
    assert "espelhar_em='tudo'" in corpo.replace('"', "'")


def test_tudo_comeca_com_buffer_limpo(fonte):
    """Log da rodada passada misturado com o de agora e' pior que log nenhum,
    porque parece progresso."""
    arvore = ast.parse(fonte)
    alvo = next(n for n in ast.walk(arvore)
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_tudo")
    corpo = ast.unparse(alvo)
    assert "_pipeline_logs['tudo'] = _LogBuffer()" in corpo.replace('"', "'")


def test_erro_da_etapa_entra_no_log(fonte):
    """Falha que so' aparece no campo `error` obriga a fechar o painel pra
    descobrir o que houve."""
    arvore = ast.parse(fonte)
    alvo = next(n for n in ast.walk(arvore)
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_and_track")
    corpo = ast.unparse(alvo)
    assert "destino.append" in corpo


def test_etapa_sem_log_responde_vazio_em_vez_de_404(fonte):
    """Abrir o painel antes de rodar qualquer coisa e' o caso comum."""
    arvore = ast.parse(fonte)
    alvo = next(n for n in ast.walk(arvore)
                if isinstance(n, ast.FunctionDef) and n.name == "pipeline_log")
    corpo = ast.unparse(alvo)
    assert "'linhas': []" in corpo.replace('"', "'")
    assert "HTTPException" not in corpo
