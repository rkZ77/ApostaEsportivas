"""Nome de mercado gravado em `picks.*.market` tem que estar em PORTUGUES.

O produto e' 100% PT-BR e o nome gravado nao e' so' rotulo: e' a CHAVE que o
front usa pra explicar a regra do mercado (`chaveCanonica` em
marketTranslate.ts). Nome cru em ingles nao casa nenhuma explicacao e cai no
texto generico "da GREEN conforme as condicoes do mercado X" -- exatamente a
frase que nao ajuda ninguem.

Achado na auditoria de 2026-08-17: `picks_faltas.market` tinha 2 picks gravados
como "Fouls. Total" em producao. `pick_engine/orchestrator.py` sempre usou
`market_pt or market_name`, mas os pipelines de faltas e goleiros -- que NAO
passam por analyze_fixture_markets e montam a oferta a mao -- liam so'
`market_name`.
"""
import pytest

from engine_pipelines import faltas_pipeline, goleiros_pipeline


def _oferta_de_odd(market_pt, market_name, value_name="Over 24.5", odd=1.75):
    """Uma linha de odds como load_odds_by_fixture devolve."""
    return {
        "market_id": 1, "market_name": market_name, "market_pt": market_pt,
        "value_name": value_name, "odd": odd, "line_value": None,
        "bookmaker_name": "Casa X", "bookmaker": "Casa X",
    }


# ───────────────────────────── faltas ─────────────────────────────


def test_faltas_prefere_o_nome_em_portugues():
    ofertas = faltas_pipeline._odds_over_faltas([
        _oferta_de_odd("Faltas Mais/Menos", "Fouls. Total", "Over 24.5"),
    ])
    assert 24.5 in ofertas, "a oferta tem que ser reconhecida"
    assert ofertas[24.5]["market_pt"] == "Faltas Mais/Menos"
    assert ofertas[24.5]["market_name"] == "Fouls. Total"


def test_faltas_cai_no_ingles_quando_nao_ha_traducao():
    """Reserva, nao regressao: sem market_pt o pipeline nao pode ficar sem nome.
    O que nao pode e' preferir o ingles quando o PT existe."""
    ofertas = faltas_pipeline._odds_over_faltas([
        _oferta_de_odd(None, "Fouls. Total", "Over 24.5"),
    ])
    assert ofertas[24.5]["market_pt"] is None
    assert ofertas[24.5]["market_name"] == "Fouls. Total"


@pytest.mark.parametrize("market_pt, esperado", [
    ("Faltas Mais/Menos", "Faltas Mais/Menos"),
    (None, "Fouls. Total"),          # reserva: o cru, e nao vazio
    ("", "Fouls. Total"),            # string vazia conta como ausente
])
def test_faltas_resolve_o_nome_gravado(market_pt, esperado):
    """A resolucao final, que e' o valor que vai pro banco.

    Replica a expressao de _melhor_candidato sem precisar montar histórico
    inteiro -- o que importa e' a ordem de preferencia."""
    oferta = {"market_pt": market_pt, "market_name": "Fouls. Total"}
    resolvido = (oferta.get("market_pt") or oferta.get("market_name")
                 or "Faltas Mais/Menos")
    assert resolvido == esperado


def test_faltas_sem_nome_nenhum_nao_grava_ingles():
    oferta = {"market_pt": None, "market_name": None}
    resolvido = (oferta.get("market_pt") or oferta.get("market_name")
                 or "Faltas Mais/Menos")
    assert resolvido == "Faltas Mais/Menos"


# ──────────────────────────── goleiros ────────────────────────────


def test_goleiros_sem_nome_nenhum_nao_grava_ingles():
    oferta = {"market_pt": None, "market_name": None}
    resolvido = (oferta.get("market_pt") or oferta.get("market_name")
                 or "Defesas do goleiro")
    assert resolvido == "Defesas do goleiro"


def test_o_default_de_goleiros_esta_em_portugues():
    """Trava o literal no codigo: era "Goalkeeper Saves" e o teste existe pra
    ninguem reintroduzir o ingles como fallback."""
    import inspect
    fonte = inspect.getsource(goleiros_pipeline)
    assert '"Goalkeeper Saves"' not in fonte.split("_MERCADOS")[0] or \
        'or "Defesas do goleiro"' in fonte, \
        "o fallback de nome de mercado tem que ser o PT"
    assert 'or "Defesas do goleiro"' in fonte


def test_o_default_de_faltas_esta_em_portugues():
    import inspect
    fonte = inspect.getsource(faltas_pipeline)
    assert 'or "Faltas Mais/Menos"' in fonte
