"""A chance que o MOTOR deu pra cada perna de um bilhete (18/10/2026).

POR QUE. Em Meus Bilhetes a "Prob. combinada" era o produto de 1/odd de cada
perna: a opiniao da CASA, com a margem dentro, e nao a do motor. O caso que
motivou: um bilhete de 8/8 e 6/6 aparecia com 43% ali e 100% na bandeja do
Raio-X. O usuario pediu os dois lado a lado: "Casa diz X%" e "Motor diz Y%".

DE ONDE. `engine_decisions.candidates` guarda, por jogo e por pipeline, cada
linha que o motor avaliou com `taxa_real` (a probabilidade estimada). Vale a
avaliacao mais recente daquela linha em qualquer pipeline: o Lecce sem gol no
1o tempo, por exemplo, foi descartado pelo piso de odd do VIP sem calcular,
mas a Multipla e o Bingo calcularam 70,6%.

COMO CASA. Perna do motor (Multipla, Bingo, Alavancagem) pelo nome do mercado
e a linha, que sao os mesmos do candidato. Perna montada pelo usuario pelo
(market_type, scope, line) do candidato, montado da perna estruturada.

CUSTO. /live/my-picks roda a cada 60s por usuario logado: a leitura e' por
jogo, no indice de fixture_id, com cache de 10 minutos. O motor roda de
madrugada, entao 10 minutos nao escondem nada.
"""
import logging

import cache_publico

logger = logging.getLogger(__name__)

_TTL = 600

#: Mercado da perna pessoal -> familia do motor (market_type sem o tempo).
_FAMILIA = {"gols": "goals", "escanteios": "corners", "cartoes": "cards"}


def _avaliacoes(cur, fixture_id: int) -> dict:
    """{"nome": {(mercado, linha): p}, "chave": {(market_type, scope, linha): p}}."""
    def ler():
        cur.execute("""
            SELECT c->>'market_name' AS nome, c->>'market_type' AS mt, c->>'scope' AS scope,
                   c->>'line' AS linha, (c->>'taxa_real')::float AS p
              FROM engine_decisions d, jsonb_array_elements(d.candidates) c
             WHERE d.fixture_id = %s AND jsonb_typeof(d.candidates) = 'array'
               AND c->>'taxa_real' IS NOT NULL
             ORDER BY d.created_at
        """, (fixture_id,))
        nome, chave = {}, {}
        # Em ordem de criacao: a avaliacao mais recente sobrescreve.
        for r in cur.fetchall():
            linha = (r["linha"] or "").strip().lower()
            if r["nome"]:
                nome[(r["nome"].strip().lower(), linha)] = r["p"]
            if r["mt"]:
                chave[(r["mt"], r["scope"] or "total", linha)] = r["p"]
        return {"nome": nome, "chave": chave}

    try:
        return cache_publico.obter(f"chance-do-motor:{fixture_id}", _TTL, ler)
    except Exception:
        # Tabela ausente (ambiente sem motor) ou banco ocupado: sem o numero,
        # a tela mostra so' o da casa.
        cur.connection.rollback()
        logger.warning("[CHANCE DO MOTOR] jogo %s", fixture_id, exc_info=True)
        return {"nome": {}, "chave": {}}


def chave_da_perna_pessoal(perna: dict) -> tuple | None:
    """(market_type, scope, linha) do candidato que corresponde a' perna
    montada no Raio-X, ou None (jogador, resultado, 2o tempo: o motor nao
    avalia esses mercados)."""
    if perna.get("tipo") != "time":
        return None
    mercado = perna.get("mercado") or ""
    periodo = perna.get("periodo") or "total"
    if periodo == "2t":
        return None
    sufixo = "_1h" if periodo == "1t" else ""
    if mercado == "btts":
        return (f"btts{sufixo}", "total", "no" if perna.get("escolha") == "nao" else "yes")
    familia = _FAMILIA.get(mercado.removesuffix("_time"))
    if not familia or perna.get("linha") is None or perna.get("direcao") not in ("mais", "menos"):
        return None
    scope = (perna.get("lado_time") or "home") if mercado.endswith("_time") else "total"
    linha = f"{'over' if perna['direcao'] == 'mais' else 'under'} {float(perna['linha']):g}"
    return (f"{familia}{sufixo}", scope, linha)


def anotar(cur, bilhetes: list) -> None:
    """Poe `prob_motor` (0..1 ou None) em cada perna dos bilhetes de varias
    pernas. A perna pessoal chega com `_chave_motor` (chave_da_perna_pessoal),
    que sai daqui; a do motor casa pelo nome do mercado e a linha."""
    for b in bilhetes:
        for leg in b.get("legs") or []:
            chave = leg.pop("_chave_motor", None)
            fid = leg.get("fixture_id")
            if not fid:
                leg["prob_motor"] = None
                continue
            av = _avaliacoes(cur, int(fid))
            if chave is not None:
                leg["prob_motor"] = av["chave"].get(chave)
            else:
                leg["prob_motor"] = av["nome"].get(
                    ((leg.get("market") or "").strip().lower(), (leg.get("line") or "").strip().lower()))
