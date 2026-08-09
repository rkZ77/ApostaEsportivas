"""Atualizacao automatica de resultado + horario do jogo no card.

Duas coisas nasceram juntas em 2026-08-09 e por isso dividem arquivo: as duas
giram em torno do horario de inicio da partida.

1. VARREDURA SOB DEMANDA (routers/live.py::maybe_resolve_pending)

   A matematica de liquidacao ja existia inteira -- resolve_all_pending resolve
   tanto o jogo encerrado quanto o pick que travou no meio (`is_locked`). O que
   faltava era gatilho: desde que o scheduler saiu (2026-08-01) ninguem a
   chamava sozinho, e o pick ficava "Pendente" no site pra todo mundo ate
   alguem abrir o /admin e clicar.

   O gatilho e' puxado por visita, e nao por relogio, pra nao repetir o consumo
   de cota que motivou a remocao do scheduler. Os testes aqui guardam os tres
   freios (relogio, banco, API) -- sem eles a feature volta a ser um job 24/7
   com outro nome.

2. HORARIO DO JOGO NO CARD (SuggestionCard.tsx)

   O card lia a hora de `match_date`, que e' coluna DATE. `new Date("2026-08-09")`
   e' meia-noite UTC, e imprimir isso em America/Sao_Paulo dava 21:00 do dia
   anterior -- em TODO pick, sempre, fosse o jogo 11:00 ou 18:30. Achado com
   dado real: Cuiaba x Fortaleza comecava 18:00 e o card dizia 21:00.

Como o resto da suite, nada aqui toca banco nem rede.
"""

import ast
import os
import re
import time

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRONT = os.path.join(os.path.dirname(_BACKEND), "frontend", "src")


def _fonte(caminho: str) -> str:
    with open(os.path.join(_BACKEND, caminho), encoding="utf-8") as f:
        return f.read()


def _front_codigo(caminho: str) -> str:
    """Fonte do componente SEM comentario -- assercao de ausencia nao pode
    casar com o comentario que EXPLICA a remocao."""
    with open(os.path.join(_FRONT, caminho), encoding="utf-8") as f:
        src = f.read()
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    return re.sub(r"(?<!:)//[^\n]*", "", src)


def _codigo(caminho: str, nome: str) -> str:
    """Fonte de uma funcao, SEM a docstring."""
    fonte = _fonte(caminho)
    for no in ast.walk(ast.parse(fonte)):
        if isinstance(no, ast.FunctionDef) and no.name == nome:
            bruto = ast.get_source_segment(fonte, no) or ""
            doc = ast.get_docstring(no, clean=False)
            return bruto.replace(doc, "") if doc else bruto
    raise AssertionError(f"funcao {nome} nao encontrada em {caminho}")


@pytest.fixture
def live(monkeypatch):
    """Modulo live com o estado da varredura zerado e sem efeito real.

    O estado e' de processo (dict de modulo), entao um teste que dispara a
    varredura contaminaria o proximo se nao fosse zerado aqui.
    """
    import routers.live as mod
    monkeypatch.setattr(mod, "_sweep_state", {"last": 0.0, "running": False})
    return mod


# ─────────────────────── Freio 1: relogio ───────────────────────


def test_varredura_nao_repete_dentro_do_intervalo(live, monkeypatch):
    """Sem trava de tempo isto viraria uma varredura POR REQUISICAO -- o front
    busca varios endpoints juntos e recarrega sozinho."""
    monkeypatch.setattr(live, "_ha_pendente_em_jogo", lambda: True)
    disparos = []
    monkeypatch.setattr(live.threading, "Thread",
                        lambda **kw: type("T", (), {"start": lambda _s: disparos.append(1)})())

    assert live.maybe_resolve_pending() is True
    live._sweep_state["running"] = False          # simula a thread terminando
    live._sweep_state["last"] = time.time()
    assert live.maybe_resolve_pending() is False  # segunda visita, mesmo minuto
    assert len(disparos) == 1


def test_varredura_em_curso_nao_ganha_outra_em_cima(live, monkeypatch):
    monkeypatch.setattr(live, "_ha_pendente_em_jogo", lambda: True)
    live._sweep_state["running"] = True
    assert live.maybe_resolve_pending() is False


def test_relogio_reinicia_no_fim_e_nao_no_comeco(live, monkeypatch):
    """Se `last` fosse marcado na largada, uma varredura mais lenta que o
    intervalo autorizaria a proxima antes de a primeira terminar."""
    corpo = _codigo("routers/live.py", "_sweep_now")
    assert '_sweep_state["last"] = time.time()' in corpo
    assert "finally" in corpo


# ─────────────────────── Freio 2: banco ───────────────────────


def test_sem_pendente_em_jogo_nao_gasta_api(live, monkeypatch):
    """A checagem e' no banco. Na maior parte do dia a resposta e' nao, e
    nenhuma chamada de API pode acontecer nesse caso."""
    monkeypatch.setattr(live, "_ha_pendente_em_jogo", lambda: False)
    chamou = []
    monkeypatch.setattr(live.threading, "Thread",
                        lambda **kw: type("T", (), {"start": lambda _s: chamou.append(1)})())
    assert live.maybe_resolve_pending() is False
    assert chamou == []


def test_pergunta_ao_banco_nao_se_repete_a_cada_request(live, monkeypatch):
    """Resposta negativa tambem reinicia o relogio: senao cada visita abriria
    conexao e rodaria as 5 queries de novo, o dia inteiro."""
    monkeypatch.setattr(live, "_ha_pendente_em_jogo", lambda: False)
    live.maybe_resolve_pending()
    assert live._sweep_state["last"] > 0
    assert live._sweep_state["running"] is False


def test_falha_na_checagem_nao_libera_varredura(live, monkeypatch):
    """Banco fora do ar nao pode virar varredura as cegas na API."""
    def _explode():
        raise RuntimeError("banco fora")
    monkeypatch.setattr(live, "_ha_pendente_em_jogo", _explode)
    assert live.maybe_resolve_pending() is False
    assert live._sweep_state["running"] is False


# ─────────────────────── Staging ───────────────────────


def test_staging_nao_varre(live, monkeypatch):
    """noprod aponta pro banco de PRODUCAO. Varrer la gravaria resultado e
    notificaria o usuario real em duplicata."""
    monkeypatch.setenv("SIDE_EFFECTS", "off")
    monkeypatch.setattr(live, "_ha_pendente_em_jogo", lambda: True)
    assert live.maybe_resolve_pending() is False


# ─────────────────────── Custo de API ───────────────────────


def test_jogo_que_nao_comecou_fica_fora_da_varredura():
    """Maior corte de custo da feature: pick publicado de manha pra jogo das
    21h nao tem nada a resolver antes das 21h, mas `match_date <= hoje` o
    inclui desde 00:00."""
    corpo = _codigo("routers/live.py", "resolve_all_pending")
    assert "_fixtures_nao_iniciadas" in corpo
    assert corpo.count("nao_iniciados") >= 5  # os 5 caminhos que gastam API


def test_corte_de_jogo_futuro_usa_relogio_de_brasilia():
    """`fixtures.match_datetime` esta gravado em horario de Brasilia sem fuso.
    Comparar com NOW() do Postgres (UTC) adiantaria o corte em 3 horas e
    liberaria pra varredura justamente os jogos que ainda nao comecaram."""
    corpo = _codigo("routers/live.py", "_fixtures_nao_iniciadas")
    assert "match_datetime > %s" in corpo
    assert "NOW()" not in corpo


def test_fixtures_vem_em_lote_e_nao_uma_a_uma():
    """/fixtures aceita 20 ids por chamada. Sem isto a varredura gastava uma
    chamada por pick pendente."""
    corpo = _codigo("routers/live.py", "resolve_all_pending")
    assert corpo.count("_fetch_fixtures_bulk") >= 4


def test_varredura_automatica_tem_janela_e_o_botao_do_admin_nao():
    """Sem janela, pick que nunca vai resolver (jogo adiado, estatistica que o
    provedor nao publicou) seria reconsultado na API pra sempre -- custo fixo
    que so' cresce. O botao do /admin continua exaustivo de proposito."""
    import routers.live as mod
    assert mod.resolve_all_pending.__defaults__ == (None,), \
        "sem argumento resolve_all_pending tem que varrer tudo, como o /admin espera"
    assert "max_age_days=_SWEEP_MAX_AGE_DAYS" in _codigo("routers/live.py", "_sweep_now")


def test_defesas_de_goleiro_ficam_fora_da_janela():
    """Goleiros resolve por player_match_stats, sem nenhuma chamada de API --
    entao nao ha cota a proteger, e a estatistica do jogador as vezes so' entra
    horas depois."""
    corpo = _codigo("routers/live.py", "resolve_all_pending")
    trecho = corpo[corpo.index("picks_goleiros"):]
    assert "{_janela}" not in trecho


# ─────────────────────── Bilhete combinado ───────────────────────


def test_perna_nao_iniciada_entra_na_lista_em_vez_de_sumir():
    """Pular a perna encurtaria a lista, e `all(r is not None)` concluiria que
    o bilhete fechou com pernas de menos -- gravando um combinado errado."""
    from routers.live import _leg_nao_iniciada, _locked_leg_result
    perna = _leg_nao_iniciada(123, "Gols Mais/Menos", "Over 2.5", 1.8)
    assert perna["is_ft"] is False and perna["is_locked"] is False
    assert _locked_leg_result(perna) is None


def test_perna_nao_iniciada_nao_inventa_placar():
    """0x0 com o jogo por comecar seria "ambas nao marcaram" -- afirmacao que
    o dado nao sustenta. O que segura o pick e' is_ft/is_locked falsos."""
    from routers.live import _leg_nao_iniciada, _multipla_combined_result
    perna = _leg_nao_iniciada(1, "Ambas Marcam", "Sim", 1.9)
    assert _multipla_combined_result([None, "GREEN"], [1.9, 2.0], 3.8) is None
    assert perna["current_val"] is None


# ─────────────────────── Gatilho ligado nas telas ───────────────────────


@pytest.mark.parametrize("caminho,funcao", [
    ("routers/suggestions.py", "get_today_suggestions"),
    ("routers/public.py", "public_results"),
])
def test_telas_de_pick_disparam_a_varredura(caminho, funcao):
    """A de dentro (assinante) e a publica (visitante deslogado). Sem a
    publica, num dia sem assinante no site o placar publico ficaria "pendente"
    com os jogos ja encerrados."""
    assert "maybe_resolve_pending()" in _codigo(caminho, funcao)


def test_gatilho_nunca_derruba_a_tela():
    """Varredura e' acessorio da resposta. Falha nela nao pode virar erro pro
    usuario que so' queria ver os picks."""
    for caminho, funcao in (("routers/suggestions.py", "get_today_suggestions"),
                            ("routers/public.py", "public_results")):
        corpo = _codigo(caminho, funcao)
        pos = corpo.index("maybe_resolve_pending()")
        assert "try:" in corpo[:pos]
        assert "except Exception" in corpo[pos:pos + 400]


def test_varredura_nao_bloqueia_a_resposta():
    """Roda em thread propria: a pagina do usuario nao espera a API-Football."""
    corpo = _codigo("routers/live.py", "maybe_resolve_pending")
    assert "threading.Thread" in corpo
    assert "daemon=True" in corpo


# ─────────────────────── Horario do jogo no card ───────────────────────


def test_card_nao_tira_hora_da_coluna_de_data():
    """`match_date` e' DATE. Virar timestamp dava 21:00 em todo pick, sempre."""
    src = _front_codigo("components/SuggestionCard.tsx")
    assert "new Date(s.match_date)" not in src
    assert "s.match_datetime" in src


def test_card_nao_reinterpreta_o_fuso_do_horario():
    """`match_datetime` ja chega em horario de Brasilia sem fuso: deixar o
    navegador interpretar joga o horario pro fuso de quem le. Mesma regra de
    home/FreePickHero.tsx e home/NextGames.tsx."""
    src = _front_codigo("components/SuggestionCard.tsx")
    assert "slice(11, 16)" in src
    assert "toLocaleTimeString" not in src


def test_backend_entrega_o_horario_pro_card():
    """O JOIN com `fixtures` ja existia nas duas consultas, mas nenhuma delas
    trazia a coluna -- o card recebia so' a data e nao tinha como acertar."""
    corpo = _codigo("routers/suggestions.py", "get_today_suggestions")
    vip = corpo[corpo.index("FROM picks_vip s"):]
    assert "f.match_datetime" in corpo[:corpo.index("FROM picks_vip s")] or \
           "f.match_datetime" in vip[:400]
    assert corpo.count("f.match_datetime") >= 2  # vip e dica do dia


def test_mercados_nao_enfiam_horario_dentro_da_data():
    """Era `match_date: p.match_datetime ?? p.match_date` -- quando o fixture
    nao estava mais na tabela caia na data pura e o card imprimia 21:00."""
    src = _front_codigo("pages/Picks.tsx")
    assert "match_date: p.match_datetime" not in src
    assert "match_datetime: p.match_datetime" in src
