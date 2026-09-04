"""Cache das rotas publicas da Home (cache_publico.py).

CONTEXTO. O PageSpeed de 04/09 anotou de 4,6 s a 6,3 s em cada uma das seis
chamadas que a Home abre junto. Medidas uma a uma elas custam 0,4 s a 1,9 s: o
que aparecia no relatorio era a FILA delas no unico worker. O cache existe pra
que a mesma pergunta, feita por visitantes diferentes no mesmo minuto, seja
respondida uma vez so.

O que estes testes seguram e' o que pode dar errado sem aparecer na tela: dado
de um usuario servido pro outro, varredura que para de rodar, e a rajada de
consultas identicas no instante em que a entrada vence.
"""
import ast
import inspect
import pathlib
import threading
import time

import cache_publico


def setup_function():
    cache_publico.invalidar()


def test_segunda_chamada_nao_recalcula():
    chamadas = []
    produzir = lambda: (chamadas.append(1), "valor")[1]

    assert cache_publico.obter("k", 60, produzir) == "valor"
    assert cache_publico.obter("k", 60, produzir) == "valor"
    assert len(chamadas) == 1


def test_ttl_vencido_recalcula():
    chamadas = []
    produzir = lambda: (chamadas.append(1), len(chamadas))[1]

    assert cache_publico.obter("k", 0.05, produzir) == 1
    time.sleep(0.08)
    assert cache_publico.obter("k", 0.05, produzir) == 2


def test_rajada_no_cache_frio_vira_uma_consulta_so():
    """Single-flight · e' o caso que motivou o arquivo.

    Sem o lock por chave, as seis chamadas simultaneas da Home que encontram a
    entrada vencida disparam seis consultas identicas -- o engarrafamento que o
    cache deveria resolver, reproduzido a cada expiracao.
    """
    chamadas = []

    def lenta():
        chamadas.append(1)
        time.sleep(0.15)
        return "pronto"

    fios = [threading.Thread(target=lambda: cache_publico.obter("k", 60, lenta))
            for _ in range(6)]
    for f in fios:
        f.start()
    for f in fios:
        f.join()

    assert len(chamadas) == 1


def test_invalidar_por_prefixo_nao_leva_o_resto():
    cache_publico.obter("public.a", 60, lambda: 1)
    cache_publico.obter("public.b", 60, lambda: 2)
    cache_publico.obter("outro.c", 60, lambda: 3)

    assert cache_publico.invalidar("public.") == 2
    assert [e["chave"] for e in cache_publico.estado()] == ["outro.c"]


def test_decorator_preserva_a_assinatura():
    """O FastAPI le a assinatura pra descobrir os query params.

    Sem o functools.wraps, `inspect.signature` enxergaria `(*args, **kwargs)` e
    a rota perderia `limit`, `days`, `slim` -- passaria a aceitar qualquer
    coisa e a ignorar tudo, sem erro nenhum.
    """
    @cache_publico.rota(60)
    def rota_fake(limit: int = 6, days: int = 180):
        return limit, days

    parametros = list(inspect.signature(rota_fake).parameters)
    assert parametros == ["limit", "days"]
    assert rota_fake(limit=1, days=2) == (1, 2)
    assert rota_fake(limit=9, days=9) == (9, 9)   # chave diferente, valor novo


def test_parametros_diferentes_nao_compartilham_entrada():
    @cache_publico.rota(60)
    def soma(a: int = 0, b: int = 0):
        return a + b

    assert soma(a=1, b=1) == 2
    assert soma(a=2, b=2) == 4


# ──────────────────────── Aplicacao nas rotas ────────────────────────────

_PUBLIC = pathlib.Path(__file__).resolve().parents[1] / "routers" / "public.py"


def _funcao(nome: str) -> ast.AST:
    arvore = ast.parse(_PUBLIC.read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        if isinstance(no, ast.FunctionDef) and no.name == nome:
            return no
    raise AssertionError(f"{nome} nao existe mais em routers/public.py")


def _decoradores(nome: str) -> str:
    return " ".join(ast.unparse(d) for d in _funcao(nome).decorator_list)


def test_rotas_da_home_estao_cacheadas():
    for nome in ("public_leagues", "public_profit_curve", "public_next_fixtures",
                 "_resultados_publicos", "_free_pick_do_dia"):
        assert "cache_publico.rota" in _decoradores(nome), nome


def test_o_endpoint_de_results_continua_agendando_as_varreduras():
    """O cache fica na funcao interna, e nao no endpoint, por causa disto.

    E' a visita que resolve resultado pendente, sincroniza estatistica e expira
    plano (nao ha nada agendado no servidor · ver a docstring de /results). Um
    cache no endpoint inteiro faria essas tres pararem no primeiro acerto.
    """
    corpo = ast.unparse(_funcao("public_results"))
    assert "background.add_task" in corpo
    assert "cache_publico" not in _decoradores("public_results")


def test_o_recorte_do_anonimo_fica_fora_do_cache():
    """Senao a primeira visita anonima definiria a resposta do logado seguinte.

    A funcao cacheada devolve a linha crua; quem apaga `market`/`line` e' o
    endpoint, depois de olhar o usuario da requisicao.
    """
    cacheada = ast.unparse(_funcao("_free_pick_do_dia"))
    endpoint = ast.unparse(_funcao("public_free_pick_today"))

    assert "locked" not in cacheada
    assert "get_current_user_optional" in endpoint
    assert "d.pop('market', None)" in endpoint
    # A copia importa tanto quanto o resto: sem ela o `pop` do anonimo apagaria
    # o mercado DENTRO do cache, e todo mundo depois receberia a versao cortada.
    assert "d = dict(d)" in endpoint


def test_escrita_no_admin_derruba_o_cache():
    main = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert "cache_publico.invalidar()" in main
    assert '/api/admin' in main
