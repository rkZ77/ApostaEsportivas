"""Probabilidade de um contador de JOGADOR passar de uma linha.

DISPERSAO MEDIDA, NAO CHUTADA
-----------------------------
Contagem de evento por jogador e' superdispersa quase sempre: um atacante que
faz 2 chutes no alvo por jogo faz 0 num jogo e 5 no outro, e Poisson afirma
que a variancia e' igual a media -- afirmacao sobre o dado, nao escolha de
formula. Onde ela e' falsa, Poisson INFLA a cauda e o motor superestima o
"N ou mais".

Este modulo NAO tras um phi por metodo escrito a mao. Ele MEDE a dispersao na
propria `player_match_stats`, a cada rodada, por metodo -- mesma decisao ja'
tomada em fouls_calibration e saves_calibration, e pelo mesmo motivo: usar pra
sempre um numero medido uma vez faz o motor envelhecer em silencio. Amostra
curta ou falha de banco devolve o `phi_congelado` do catalogo.

A conta em si e' reusada de services/pick_engine/probability_model.py (Binomial
Negativa / Gama-Poisson, que devolve Poisson exato quando phi = 1). Nao ha'
segunda implementacao de nb_pmf no projeto, e nao pode haver: duas
implementacoes da mesma distribuicao acabam divergindo na cauda, que e'
justamente onde o pick vive.
"""
from __future__ import annotations

from services.pick_engine import probability_model as pm
from services.player_stats_engine import methods as cat
from utils.db_utils import linha_dict

#: Abaixo disto a variancia medida e' ruido. Um phi estimado com 40 atuacoes
#: nao e' uma medida, e' uma opiniao com casas decimais.
MIN_ATUACOES_PARA_CALIBRAR = 120

#: Teto de seguranca. phi absurdo (dado sujo, coluna trocada na coleta)
#: achataria a probabilidade a quase zero e o motor pararia sem dizer porque.
PHI_MAX = 6.0


def medir_dispersao(cur, metodo: cat.Metodo) -> dict:
    """variancia/media do contador do metodo, na base inteira.

    Devolve sempre um dicionario com `phi`, `origem` e `atuacoes` -- a origem
    e' o que permite explicar, meses depois, por que dois picks com a mesma
    entrada deram probabilidades diferentes.
    """
    congelado = {"phi": metodo.phi_congelado, "origem": "congelada",
                 "atuacoes": 0, "erro": None}
    try:
        cur.execute(f"""
            SELECT COUNT(*) AS n,
                   AVG({metodo.coluna}::numeric)      AS media,
                   VAR_POP({metodo.coluna}::numeric)  AS variancia
              FROM player_match_stats
             WHERE {metodo.coluna} IS NOT NULL
               AND COALESCE(minutes, 0) >= 60
        """)
        linha = linha_dict(cur)
        if not linha:
            return congelado
        n = int(linha.get("n") or 0)
        media = float(linha.get("media") or 0)
        variancia = float(linha.get("variancia") or 0)
        if n < MIN_ATUACOES_PARA_CALIBRAR or media <= 0:
            return {**congelado, "atuacoes": n}
        phi = variancia / media
        # phi < 1 e' subdispersao. Existe (contador com teto natural), mas a
        # Gama-Poisson nao a representa -- truncar em 1.0 volta pra Poisson,
        # que e' o caso limite correto.
        phi = min(max(phi, 1.0), PHI_MAX)
        return {"phi": round(phi, 3), "origem": "medida", "atuacoes": n,
                "media_base": round(media, 3), "erro": None}
    except Exception as e:
        return {**congelado, "erro": str(e)[:200]}


def calibragem_de_todos(cur, metodos=None) -> dict:
    """{slug: calibragem} pra a rodada inteira. Uma consulta por metodo."""
    return {m.slug: medir_dispersao(cur, m) for m in (metodos or cat.METODOS)}


def media_ponderada(valores: list, peso_recente: float = 1.6) -> float | None:
    """Media das atuacoes, com o passado recente pesando mais.

    A lista chega do mais recente pro mais antigo. O peso decai linearmente de
    `peso_recente` ate' 1.0 -- decaimento suave de proposito: um exponencial
    forte transformaria a estimativa no ultimo jogo, e um jogo e' ruido.
    """
    valores = [float(v) for v in valores if v is not None]
    if not valores:
        return None
    n = len(valores)
    if n == 1:
        return round(valores[0], 3)
    pesos = [peso_recente - (peso_recente - 1.0) * (i / (n - 1)) for i in range(n)]
    return round(sum(v * p for v, p in zip(valores, pesos)) / sum(pesos), 3)


def analisar(*, valores: list, linha: float, phi: float, odd: float | None = None,
             ajuste_adversario: float | None = None) -> dict | None:
    """Candidato pra UMA linha de UM jogador, ou None se nao der pra avaliar.

    `linha` ja' vem na convencao de meia-linha. O mercado publica "N ou mais",
    que e' P(X >= N) -- quem chama converte pra N - 0.5 antes, exatamente como
    o pipeline de goleiros sempre fez. Passar N direto contaria um evento a
    menos e superestimaria o pick.

    `ajuste_adversario` e' um multiplicador (1.0 = neutro) pra os metodos que
    dependem do outro time. Fica explicito no retorno pra a explicacao poder
    dizer que ele existiu.
    """
    mu = media_ponderada(valores)
    if mu is None or mu <= 0:
        return None
    mu_ajustado = mu
    if ajuste_adversario:
        mu_ajustado = round(mu * float(ajuste_adversario), 3)

    prob = pm.prob_over(linha, mu_ajustado, phi)
    if not prob or prob <= 0 or prob >= 1:
        return None

    resultado = {
        "linha": linha,
        "esperado": mu_ajustado,
        "esperado_bruto": mu,
        "ajuste_adversario": ajuste_adversario,
        "phi": phi,
        "amostra": len(valores),
        "probability": round(prob, 4),
        "fair_odd": round(1 / prob, 3),
    }
    if odd and odd > 1:
        resultado["odd"] = float(odd)
        resultado["edge"] = round(prob - 1 / float(odd), 4)
        # EV por unidade apostada, mesma formula do goalkeeper_model.
        resultado["ev"] = round(prob * (float(odd) - 1) - (1 - prob), 4)
    return resultado
