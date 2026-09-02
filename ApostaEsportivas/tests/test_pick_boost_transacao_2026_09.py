"""O Pick Boost nao pode morrer inteiro por causa de um jogo.

Dois defeitos que juntos mantiveram o motor em FAILED com 0 analisados desde
2026-08-31, e nenhum deles aparecia como bug no codigo lido isoladamente.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services.pick_engine_boost import goals_history


def test_nome_do_adversario_devolve_uma_linha_so():
    """`teams` tem uma linha por (team_id, season) -- Flamengo aparece tres
    vezes. Sem LIMIT a subconsulta escalar estoura 'more than one row', aborta
    a transacao e leva a execucao inteira junto."""
    sql = goals_history._nome_do_adversario("ms.away_team_id")
    assert "LIMIT 1" in sql, "subconsulta escalar sobre teams precisa de LIMIT 1"
    assert "ORDER BY" in sql, "sem ORDER BY o LIMIT devolve temporada arbitraria"
    assert "season" in sql, "o desempate certo e' a temporada mais recente"


def test_o_padrao_e_o_mesmo_do_resto_do_projeto():
    """admin.py resolve isso com `ORDER BY season DESC LIMIT 1` em seis
    consultas equivalentes. Este era o unico ponto fora do padrao."""
    sql = goals_history._nome_do_adversario("x")
    normalizado = " ".join(sql.split()).lower()
    assert "order by t.season desc limit 1" in normalizado


def test_on_conflict_cita_as_tres_colunas_do_indice_unico():
    """`idx_picks_boost_dia_jogo` e' UNIQUE (match_date, fixture_id,
    market_type). Um ON CONFLICT com duas dessas tres nao casa com constraint
    nenhuma, e o Postgres recusa o INSERT inteiro -- erro que so' aparece na
    GRAVACAO, depois de o motor ter avaliado tudo.

    Este teste le o SQL do arquivo em vez de exigir banco: o descasamento e'
    entre dois textos, e e' assim que ele se manifesta."""
    import os
    caminho = os.path.join(os.path.dirname(__file__), "..", "src",
                           "engine_pipelines", "pick_boost_pipeline.py")
    with open(caminho, encoding="utf-8") as f:
        fonte = f.read()
    linhas = [l for l in fonte.splitlines()
              if "ON CONFLICT" in l and not l.strip().startswith(("--", "#"))]
    assert linhas, "o INSERT do boost perdeu o ON CONFLICT"
    for linha in linhas:
        for coluna in ("match_date", "fixture_id", "market_type"):
            assert coluna in linha, (
                f"ON CONFLICT sem `{coluna}`: nao casa com idx_picks_boost_dia_jogo")
