"""Home: fila de jogos publica, Dica do Dia com reserva e peso da pagina.

Como o resto da suite, nada aqui toca banco: o que se verifica e a forma do
SQL e o acoplamento entre tela e rota, que e onde os tres bugs desta leva
moravam.
"""

import ast
import os
import re

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRONT = os.path.join(os.path.dirname(_BACKEND), "frontend", "src")


def _fonte(caminho: str) -> str:
    with open(os.path.join(_BACKEND, caminho), encoding="utf-8") as f:
        return f.read()


def _front(caminho: str) -> str:
    with open(os.path.join(_FRONT, caminho), encoding="utf-8") as f:
        return f.read()


def _codigo(caminho: str, nome: str) -> str:
    """Fonte de uma funcao, SEM a docstring.

    Recortar por texto ("do def ate o proximo @router") mordia o que viesse
    depois e, pior, deixava a prosa dentro da amostra: a primeira versao destes
    testes passava a ler os proprios comentarios e dava tanto falso positivo
    quanto falso negativo. Aqui o recorte e sintatico.
    """
    fonte = _fonte(caminho)
    for no in ast.walk(ast.parse(fonte)):
        if isinstance(no, ast.FunctionDef) and no.name == nome:
            bruto = ast.get_source_segment(fonte, no) or ""
            doc = ast.get_docstring(no, clean=False)
            return bruto.replace(doc, "") if doc else bruto
    raise AssertionError(f"funcao {nome} nao encontrada em {caminho}")


# ─────────────────────── Fila de jogos na Home ─────────────────────────


def test_fila_da_home_nao_depende_de_sessao():
    """A faixa e' pra visitante anonimo, entao a rota tem que ser publica.

    Ela lia GET /api/fixtures/today, que exige login: pro publico da Home o
    resultado era sempre 401, e a faixa nunca aparecia pra ninguem deslogado.
    """
    src = _front("home/NextGames.tsx")
    assert "/public/next-fixtures" in src
    assert "/fixtures/today" not in src

    # e a rota nova precisa mesmo ser publica -- sem Depends de usuario
    corpo = _codigo("routers/public.py", "public_next_fixtures")
    assert "current_user" not in corpo
    assert "Depends" not in corpo


def test_fila_corta_pelo_relogio_de_brasilia():
    """`fixtures.match_datetime` esta gravado em horario de Brasilia sem fuso.

    Comparar com NOW() puro (o banco roda em UTC) adiantaria o corte em 3
    horas e esconderia justamente os jogos da tarde.
    """
    corpo = _codigo("routers/public.py", "public_next_fixtures")
    assert "NOW() AT TIME ZONE '{TZ_BR}'" in corpo
    assert re.search(r"NOW\(\)\s*[<>=]", corpo) is None


def test_fila_e_daqui_pra_frente_e_nao_do_dia():
    """A queixa era "quando acabam os jogos de hoje, mostrar os de amanha".

    Filtrar por data presa a hoje devolve partida que ja rolou e deixa a faixa
    vazia no fim do dia; o corte tem que ser por horario, sem travar no dia.
    """
    corpo = _codigo("routers/public.py", "public_next_fixtures")
    assert "match_datetime >=" in corpo
    assert "::date =" not in corpo
    assert "ORDER BY f.match_datetime" in corpo


def test_fila_tem_indice_pra_nao_varrer_a_tabela():
    src = _fonte("migrations.py")
    assert "idx_fixtures_proximos" in src
    idx = src[src.index("idx_fixtures_proximos") - 40:]
    assert "IF NOT EXISTS" in idx[:120]


# ─────────────────── Dica do Dia: hoje, ou a anterior ──────────────────


def test_dica_do_dia_usa_data_brasileira():
    """CURRENT_DATE e' a data UTC: entre 21h e meia-noite de Brasilia o banco
    ja virou o dia e o Brasil nao, e a dica sumia da Home no horario de pico."""
    corpo = _codigo("routers/public.py", "public_free_pick_today")
    assert "HOJE_BR" in corpo
    assert "CURRENT_DATE" not in corpo


def test_dica_cai_na_anterior_quando_o_dia_ainda_nao_tem_pick():
    """Sem pick de hoje a rota devolvia None e a Home ficava com um buraco.

    Nao existe horario fixo de publicacao desde 01/08, entao esse buraco podia
    durar o dia inteiro.
    """
    corpo = _codigo("routers/public.py", "public_free_pick_today")
    assert "match_date <" in corpo, "falta a consulta de reserva"
    assert 'd["is_previous"] = is_previous' in corpo
    # a reserva tem que ser a MAIS RECENTE das antigas
    assert "ORDER BY pf.match_date DESC" in corpo


def test_reserva_nao_derruba_o_bloqueio_de_mercado():
    """O ramo do anonimo continua sendo o primeiro `else` da funcao.

    E' o mesmo invariante do test_deploy_prod_2026_08; repetido aqui porque a
    consulta de reserva entrou logo acima dele e um `else` novo no caminho
    quebraria o corte sem quebrar nenhum teste de la.
    """
    corpo = _codigo("routers/public.py", "public_free_pick_today")
    ramo_anon = corpo[corpo.index("else:"):]
    assert 'd.pop("market", None)' in ramo_anon
    assert 'd["locked"] = True' in ramo_anon


def test_tela_trata_a_dica_anterior_como_historico():
    """Card antigo tem que dizer que e' antigo -- com data e resultado --
    em vez de se passar pela dica de hoje."""
    src = _front("home/FreePickHero.tsx")
    assert "is_previous" in src
    assert "Última dica publicada" in src


# ──────────────────────── Peso da pagina ───────────────────────────────


def test_home_nao_pede_mais_recentes_do_que_mostra():
    """Pedia 50 e renderizava 10: o backend roda uma sub-query por tipo de
    pick, entao o excesso multiplicava por seis do lado do banco."""
    src = _front("pages/Home.tsx")
    pedido = re.search(r"recent_limit:\s*(\d+)", src)
    mostrado = re.search(r"\.recent\s*\?\?\s*\[\]\)\.slice\(0,\s*(\d+)\)", src)
    assert pedido and mostrado
    assert int(pedido.group(1)) == int(mostrado.group(1))


def test_resposta_da_api_sai_comprimida():
    """O dist/ e servido pelo proprio FastAPI, sem nginx na frente: sem este
    middleware nada no site era comprimido, nem JSON nem bundle."""
    src = _fonte("main.py")
    assert "GZipMiddleware" in src
    # registrado antes do CORS pra que o CORS seja a camada de fora
    assert src.index("add_middleware(GZipMiddleware") < src.index("CORSMiddleware,")


def test_bundle_com_hash_nao_revalida_a_cada_carregamento():
    src = _fonte("main.py")
    assert "immutable" in src
    # e o index.html tem que ser o oposto, senao o deploy novo nao chega
    assert '"Cache-Control": "no-cache"' in src


def test_ligas_da_home_sao_buscadas_uma_vez_so():
    """A Home monta duas fitas de ligas; cada uma disparava a sua propria
    chamada pra mesma lista."""
    src = _front("components/LeagueMarquee.tsx")
    assert "_leaguesPromise" in src
    assert src.count("api.get(") == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
