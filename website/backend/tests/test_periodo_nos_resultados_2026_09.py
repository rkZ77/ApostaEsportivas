"""A página de Resultados filtra por DIA, não só por mês.

"Como foi ontem" era a pergunta que a tela não sabia responder: quase todo jogo
termina de madrugada, então de manhã "este mês" mistura a rodada que acabou de
fechar com as três semanas anteriores.

O recorte é o mesmo vocabulário da Banca e do Meus Picks (frontend/src/lib/
periodo.ts) e governa a página inteira, porque a janela viaja pro backend e
todos os blocos da resposta leem o mesmo `date_cond`.
"""
import re
from pathlib import Path

from routers.public import _janela_de_datas

FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _ler(caminho: str) -> str:
    return (FRONT / caminho).read_text(encoding="utf-8")


# ── A janela, no backend ───────────────────────────────────────────────────
class TestJanelaDeDatas:
    def test_par_bem_formado_vira_janela(self):
        assert _janela_de_datas("2026-09-10", "2026-09-10") == ("2026-09-10", "2026-09-10")

    def test_meia_janela_nao_filtra(self):
        """`from_date` sozinho mostraria tudo desde uma data ate' o fim dos
        tempos, e quem pediu "Ontem" receberia ontem, hoje e o futuro."""
        assert _janela_de_datas("2026-09-10", None) is None
        assert _janela_de_datas(None, "2026-09-10") is None

    def test_formato_errado_nao_filtra_em_vez_de_derrubar_a_pagina(self):
        """A data entra como parametro, entao o risco nao e' injecao: e' o
        Postgres levantar DataError no meio de uma pagina publica."""
        assert _janela_de_datas("10/09/2026", "11/09/2026") is None
        assert _janela_de_datas("2026-9-1", "2026-09-11") is None
        assert _janela_de_datas("ontem", "hoje") is None

    def test_janela_invertida_nao_vira_resultado_vazio(self):
        """Vazio pareceria "nenhum resultado no periodo", que e' uma resposta
        errada pra uma pergunta mal feita."""
        assert _janela_de_datas("2026-09-11", "2026-09-10") is None


def test_o_endpoint_aceita_a_janela():
    from routers.public import public_results
    import inspect

    params = inspect.signature(public_results).parameters
    assert "from_date" in params
    assert "to_date" in params
    # `month` continua: a Home e qualquer link salvo ainda mandam ele.
    assert "month" in params


def test_a_janela_ganha_do_mes():
    """Os dois podem chegar juntos; o recorte mais especifico manda."""
    fonte = Path(__file__).resolve().parents[1] / "routers" / "public.py"
    sql = fonte.read_text(encoding="utf-8")
    i_janela = sql.index("janela = _janela_de_datas(from_date, to_date)")
    i_mes = sql.index("elif month:", i_janela)
    assert i_janela < i_mes


def test_o_cache_separa_as_janelas():
    """A chave do cache sai dos ARGUMENTOS da funcao decorada (ver
    cache_publico.rota). Se `from_date`/`to_date` nao chegassem ate' ela, uma
    visita a "Ontem" serviria a resposta de "Hoje" por ate' 60 segundos."""
    fonte = Path(__file__).resolve().parents[1] / "routers" / "public.py"
    sql = fonte.read_text(encoding="utf-8")
    assinatura = re.search(r"def _resultados_publicos\((.*?)\):", sql, re.S).group(1)
    assert "from_date" in assinatura
    assert "to_date" in assinatura


# ── O recorte, na tela ─────────────────────────────────────────────────────
class TestUmFiltroSo:
    def test_a_pagina_usa_o_vocabulario_compartilhado(self):
        tela = _ler("pages/ResultadosPublicos.tsx")
        assert "from '../lib/periodo'" in tela
        assert "PERIODOS" in tela
        assert "janelaDoPeriodo" in tela

    def test_a_janela_vai_pro_backend(self):
        tela = _ler("pages/ResultadosPublicos.tsx")
        assert "params.from_date" in tela
        assert "params.to_date" in tela

    def test_os_meses_ficam_na_mesma_lista_do_periodo(self):
        """Fila separada seria o segundo controle de data que a tela ja' teve e
        perdeu de proposito em 04/09."""
        tela = _ler("pages/ResultadosPublicos.tsx")
        assert "mes:${m}" in tela
        assert tela.count('ariaLabel="Mês"') == 0

    def test_a_aba_por_jogo_recebe_o_mesmo_recorte(self):
        """Ela filtrava so' por mes, entao "Ontem" nao chegava nela e a lista
        ficava no mes inteiro enquanto o resto da pagina respondia pelo dia."""
        tela = _ler("pages/ResultadosPublicos.tsx")
        assert "fetchGames(0, gamesFilter, source, periodo)" in tela
        assert "monthDateRange" not in tela


def test_ontem_existe_no_vocabulario():
    periodo = _ler("lib/periodo.ts")
    assert "'ontem'" in periodo
    assert "label: 'Ontem'" in periodo
