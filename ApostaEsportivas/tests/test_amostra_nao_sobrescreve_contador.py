"""O bloco da amostra nunca ocupa a chave do contador de jogos.

BUG DE PRODUÇÃO (2026-09-24). Cinco pipelines montavam o pick como
`{**candidato, "amostra": amostra.build(...)}`, trocando o CONTADOR de jogos
pelo BLOCO da amostra (um dicionário com a lista de jogos dos dois times, ver
services/engine_audit/amostra.py). Duas consequências, nenhuma delas visível em
teste até hoje:

  · o texto que o assinante lê saía com o dicionário dentro da frase --
    "Taxa real ponderada de 60.1% em {'max_exibidos': 10, ...} jogos", 8 mil
    caracteres de JSON num campo de leitura. Aconteceu em 239 picks desde
    27/08 e ninguém viu, porque nada compara texto de reasoning;
  · quando a ressalva de amostra passou a COMPARAR o valor com um número, o
    pipeline da Free morreu em produção com
    "TypeError: '<' not supported between instances of 'dict' and 'int'".

A raiz está corrigida (o bloco mora em `amostra_exibida`) e a guarda também: a
explicação nunca publica o que não é número. Estes testes travam os dois, porque
a raiz depende de cinco arquivos lembrarem do nome certo.
"""
from services.pick_engine import homologation
from services.pick_engine.explanation import build_explanation


#: O bloco, reduzido ao que importa: é um dict, e não um número.
BLOCO_DA_AMOSTRA = {
    "max_exibidos": 10,
    "mandante": {"team_id": 140, "time": "Criciuma", "jogos_lidos": 14,
                 "jogos": [{"data": "2026-09-09", "gols_total": 2.0}]},
    "visitante": {"team_id": 144, "time": "Novorizontino", "jogos_lidos": 12,
                  "jogos": []},
}


def candidato(**extra) -> dict:
    base = {
        "market_name": "Gols Mais/Menos", "value_label": "Under 2.5",
        "market_type": "goals", "value": "under", "odd": 1.62,
        "taxa_real": 0.669, "ev": 0.084, "edge": 0.05, "confidence": 0.84,
        "amostra": 12, "amostra_label": "RICO", "bookmakers_count": 3,
        "risco": "ALTO", "final_score": 1.0, "stake_units": 1,
    }
    base.update(extra)
    return base


def texto_de(candidato_: dict) -> str:
    exp = build_explanation(candidato_)
    return " | ".join(exp["positive_factors"] + exp["negative_factors"] + exp["risks"])


# ── A guarda: a explicação não publica dicionário e não estoura ───────────
def test_explicacao_nao_estoura_com_o_bloco_no_lugar_do_numero():
    """Era um TypeError em produção, não um texto feio."""
    texto = texto_de(candidato(amostra=BLOCO_DA_AMOSTRA))

    assert "Taxa real ponderada" in texto


def test_explicacao_omite_a_contagem_em_vez_de_imprimir_o_dicionario():
    """Omitir é o certo: a frase fica mais pobre e continua verdadeira.
    Inventar um número seria pior que não ter."""
    texto = texto_de(candidato(amostra=BLOCO_DA_AMOSTRA))

    assert "max_exibidos" not in texto
    assert "team_id" not in texto
    assert "jogos_lidos" not in texto
    assert "{" not in texto


def test_com_numero_a_frase_continua_dizendo_quantos_jogos():
    assert "em 12 jogos" in texto_de(candidato(amostra=12))


def test_amostra_ausente_nao_inventa_contagem():
    texto = texto_de(candidato(amostra=None))

    assert "Taxa real ponderada" in texto
    assert "jogos" not in texto.split("|")[0]


# ── A raiz: o retrato do candidato guarda NÚMERO em `amostra` ─────────────
def test_retrato_do_candidato_guarda_o_numero_e_nao_o_bloco():
    """`homologation.build_score_breakdown_section` alimenta o engine_debug, que
    é de onde a auditoria de RED lê o n. Com o bloco aqui, a pergunta "71%
    apoiado em quantos jogos?" volta a não ter resposta."""
    retrato = homologation.build_score_breakdown_section(
        candidato(amostra=12, amostra_exibida=BLOCO_DA_AMOSTRA))

    assert retrato["amostra"] == 12
