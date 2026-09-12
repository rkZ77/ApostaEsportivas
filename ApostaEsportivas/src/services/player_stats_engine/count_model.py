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


#: Com quantas atuacoes no mando de hoje a media daquele mando passa a valer
#: metade da estimativa. Cinco e' baixo de proposito: o mando nao e' um jogador
#: diferente, e' um deslocamento -- e a media geral, que entra no outro prato da
#: balanca, ja' contem metade dos jogos daquele mesmo mando.
K_MANDO = 5


def media_com_mando(valores: list, valores_no_mando: list) -> dict:
    """§7 -- a media geral puxada na direcao do que o jogador faz NESTE mando.

    O §7 e' explicito sobre os dois erros opostos: usar so' a media geral
    quando existe amostra de mando, e deixar a amostra pequena de mando dominar
    o calculo. O encolhimento resolve os dois de uma vez -- com duas atuacoes em
    casa o mando quase nao move a estimativa, com dez ele move de verdade.
    """
    geral = media_ponderada(valores)
    do_mando = media_ponderada(valores_no_mando or [])
    n_mando = len([v for v in (valores_no_mando or []) if v is not None])
    if geral is None:
        return {"media": None, "geral": None, "mando": do_mando,
                "amostra_mando": n_mando, "peso_mando": 0.0}
    if do_mando is None or n_mando <= 0:
        return {"media": geral, "geral": geral, "mando": None,
                "amostra_mando": 0, "peso_mando": 0.0}
    peso = n_mando / (n_mando + K_MANDO)
    return {
        "media": round(geral * (1 - peso) + do_mando * peso, 3),
        "geral": geral, "mando": do_mando,
        "amostra_mando": n_mando, "peso_mando": round(peso, 3),
    }


def analisar(*, valores: list, linha: float, phi: float, odd: float | None = None,
             ajuste_adversario: float | None = None,
             ajuste_minutos: float | None = None,
             valores_no_mando: list | None = None,
             penalidade_variancia: float = 0.0,
             desconto_contradicao: float = 0.0) -> dict | None:
    """Candidato pra UMA linha de UM jogador, ou None se nao der pra avaliar.

    `linha` ja' vem na convencao de meia-linha. O mercado publica "N ou mais",
    que e' P(X >= N) -- quem chama converte pra N - 0.5 antes, exatamente como
    o pipeline de goleiros sempre fez. Passar N direto contaria um evento a
    menos e superestimaria o pick.

    `ajuste_adversario` e' um multiplicador (1.0 = neutro) pra os metodos que
    dependem do outro time. Fica explicito no retorno pra a explicacao poder
    dizer que ele existiu.
    """
    mando = media_com_mando(valores, valores_no_mando)
    mu = mando["media"]
    if mu is None or mu <= 0:
        return None
    # A ordem dos dois ajustes nao importa (sao multiplicativos), mas eles sao
    # aplicados SEPARADAMENTE e guardados SEPARADAMENTE: um multiplicador unico
    # ja' aplicado torna impossivel responder, dois meses depois, se a projecao
    # subiu pelo adversario ou caiu pelos minutos.
    mu_ajustado = mu
    if ajuste_adversario:
        mu_ajustado = mu_ajustado * float(ajuste_adversario)
    if ajuste_minutos:
        mu_ajustado = mu_ajustado * float(ajuste_minutos)
    mu_ajustado = round(mu_ajustado, 3)

    prob = pm.prob_over(linha, mu_ajustado, phi)
    if not prob or prob <= 0 or prob >= 1:
        return None

    base = {
        "linha": linha,
        "esperado": mu_ajustado,
        "esperado_bruto": mando["geral"],
        "esperado_no_mando": mando["mando"],
        "peso_do_mando": mando["peso_mando"],
        "amostra_no_mando": mando["amostra_mando"],
        "ajuste_adversario": ajuste_adversario,
        "ajuste_minutos": ajuste_minutos,
        "phi": phi,
        "amostra": len(valores),
        "probability_modelo": round(prob, 4),
        "odd": float(odd) if odd and odd > 1 else None,
    }
    return aplicar_abatimento(base, penalidade_variancia=penalidade_variancia,
                              desconto_contradicao=desconto_contradicao)


#: Teto do abatimento somado. Alem de 20 pontos de probabilidade o que existe
#: nao e' um pick descontado: e' um pick que o motor nao sabe avaliar, e o lugar
#: dele e' o NO_PICK -- que e' onde as contradicoes CRITICAS ja' o colocam.
ABATIMENTO_MAX = 0.20


def aplicar_abatimento(analise: dict, *, penalidade_variancia: float = 0.0,
                       desconto_contradicao: float = 0.0) -> dict:
    """§18, §25, §26 -- da probabilidade do MODELO pra a CALIBRADA, e o resto.

    UMA IMPLEMENTACAO SO', e por um motivo concreto: o metodo `saves` nao passa
    por `analisar` (ele vem do goalkeeper_model, que foi medido e nao e'
    reescrito), e os outros cinco passam. Se o desconto e a aritmetica de
    edge/EV existissem nos dois caminhos, seria questao de tempo ate' `saves`
    calibrar diferente de `shots` sem ninguem perceber -- e' exatamente o que
    aconteceu com o contexto de competicao na migracao de 27/08.

    A do modelo responde "dada esta media e esta dispersao, com que frequencia
    o evento acontece". A calibrada responde a mesma pergunta DESCONTANDO o que
    o motor sabe que nao esta' na conta: dispersao do jogador acima do normal do
    contador, e contradicoes que ele nao conseguiu precificar de outro jeito.

    As duas ficam gravadas. O edge, o EV e a odd justa saem da CALIBRADA (§25 e
    §26: "nao usar probabilidade bruta inflada"), e a do modelo fica pra a
    auditoria poder medir o tamanho do desconto contra o resultado real.
    """
    prob = analise.get("probability_modelo")
    if prob is None:
        prob = analise.get("probability")
    if prob is None:
        return analise
    prob = float(prob)

    abatimento = round(min(float(penalidade_variancia or 0)
                           + float(desconto_contradicao or 0), ABATIMENTO_MAX), 4)
    prob_calibrada = round(max(prob - abatimento, 0.01), 4)

    resultado = {
        **analise,
        "probability_modelo": round(prob, 4),
        "abatimento": abatimento,
        "penalidade_variancia": round(float(penalidade_variancia or 0), 4),
        "desconto_contradicao": round(float(desconto_contradicao or 0), 4),
        # `probability` continua sendo a chave que o resto do motor le' -- e ela
        # aponta pra CALIBRADA. Trocar o nome pareceria mais honesto e quebraria
        # em silencio o Score, a gravacao, o ledger e a tela, que a leem por
        # este nome ha' meses.
        "probability": prob_calibrada,
        "probability_calibrada": prob_calibrada,
        "fair_odd": round(1 / prob_calibrada, 3),
    }
    odd = analise.get("odd")
    if odd and float(odd) > 1:
        odd = float(odd)
        resultado["odd"] = odd
        resultado["implied_probability"] = round(1 / odd, 4)
        resultado["edge"] = round(prob_calibrada - 1 / odd, 4)
        # EV por unidade apostada, mesma formula do goalkeeper_model.
        resultado["ev"] = round(prob_calibrada * (odd - 1) - (1 - prob_calibrada), 4)
    return resultado
