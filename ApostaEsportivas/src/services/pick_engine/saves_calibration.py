"""Recalibracao das constantes de defesas de goleiro, a cada rodada.

MESMO MOTIVO DO fouls_calibration, OUTRO FORMATO
------------------------------------------------
goalkeeper_model tem tres numeros medidos uma vez, em 2026-08-01, contra 1892
atuacoes:

    SAVE_RATE_PER_SHOT_ON = 0.678   defesas por chute no alvo sofrido
    LEAGUE_MEAN_SAVES     = 2.54    media da liga, usada como prior de encolhimento
    DISPERSION_R          = 3.19    dispersao da Binomial Negativa, por momentos

Diferente de faltas, aqui nao ha' tabela de faixas: o modelo e' parametrico,
entao recalibrar e' recalcular tres escalares. Isso torna a operacao MAIS segura
que a de faltas -- nao existe mapeamento faixa -> taxa pra descasar. O que muda
e' a media esperada e a forma da distribuicao, que e' exatamente o que deveria
acompanhar a base crescendo.

A PENDENCIA QUE ISTO ENDERECA EM PARTE
--------------------------------------
O docstring de goalkeeper_model valida a Binomial Negativa so' na linha Over 1.5
(erra 0.7pp) e registra "erro absoluto acumulado de 14.8pp" nas demais, sem
dizer a direcao. As ofertas reais quase sempre sao 2.5 e 3.5. Recalcular `r`
contra a base atual nao responde essa pergunta sozinho, mas para de responder
com a dispersao de um recorte de agosto.

O QUE ELE NAO FAZ: nao mexe em quantos chutes no alvo o adversario produz, que
sai do historico do time no pipeline. Aqui so' vive a relacao chute -> defesa e
a forma da distribuicao.
"""
from __future__ import annotations

from statistics import variance

from services.pick_engine import goalkeeper_model as gm

#: Minimo de atuacoes de goleiro pra a recalibragem substituir as constantes.
#:
#: ESCOLHIDO, NAO MEDIDO. As constantes congeladas vieram de 1892 atuacoes;
#: trocar isso por um numero tirado de 200 seria perder precisao em nome de
#: frescor. 400 e' o ponto em que a media da liga ja' estabiliza o suficiente
#: pra o prior de encolhimento nao ficar pior que o antigo.
MIN_ATUACOES = 400


def carregar_atuacoes(cur) -> list:
    """[(defesas, chutes_no_alvo_sofridos)] por atuacao de goleiro.

    Duas atuacoes por jogo, uma de cada lado. O par certo importa e ja' custou
    caro uma vez: `home_goalkeeper_saves` e' a defesa do goleiro da casa contra
    os chutes do VISITANTE (`away_shots_on`). Cruzar o mesmo lado inverte a
    relacao inteira.
    """
    cur.execute("""
        SELECT home_goalkeeper_saves, away_shots_on,
               away_goalkeeper_saves, home_shots_on
        FROM match_statistics
        WHERE home_goalkeeper_saves IS NOT NULL
          AND away_goalkeeper_saves IS NOT NULL
          AND home_shots_on IS NOT NULL
          AND away_shots_on IS NOT NULL
    """)
    atuacoes = []
    for casa_defesas, fora_chutes, fora_defesas, casa_chutes in cur.fetchall():
        atuacoes.append((float(casa_defesas), float(fora_chutes)))
        atuacoes.append((float(fora_defesas), float(casa_chutes)))
    return atuacoes


def medir(atuacoes: list) -> dict | None:
    """As tres constantes a partir das atuacoes, ou None se nao der pra medir."""
    if len(atuacoes) < 2:
        return None

    defesas = [d for d, _ in atuacoes]
    total_defesas = sum(defesas)
    total_chutes = sum(c for _, c in atuacoes)

    mu = total_defesas / len(defesas)
    var = variance(defesas)

    # r = mu^2 / (var - mu) so' existe quando ha' superdispersao. Se a base
    # deixar de ser superdispersa (var <= mu), a Binomial Negativa nao e' o
    # modelo certo e recalibrar `r` seria forcar uma formula que nao cabe --
    # devolve None e a constante congelada continua valendo.
    r = (mu * mu) / (var - mu) if var > mu and mu > 0 else None

    return {
        "save_rate_per_shot_on": (total_defesas / total_chutes) if total_chutes else None,
        "league_mean_saves": mu,
        "dispersion_r": r,
        "base_rate_over_15": sum(1 for d in defesas if d >= 2) / len(defesas),
        "atuacoes": len(defesas),
        "variancia_sobre_media": (var / mu) if mu else None,
    }


def _congeladas() -> dict:
    return {
        "save_rate_per_shot_on": gm.SAVE_RATE_PER_SHOT_ON,
        "league_mean_saves": gm.LEAGUE_MEAN_SAVES,
        "dispersion_r": gm.DISPERSION_R,
        "base_rate_over_15": gm.BASE_RATE_OVER_15,
    }


def recalibrar(cur, min_atuacoes: int = MIN_ATUACOES) -> tuple[dict, dict]:
    """(constantes, diagnostico). Nunca levanta: falha devolve as congeladas.

    Substitui campo a campo, nao o bloco inteiro: se a dispersao nao puder ser
    medida (base sem superdispersao) mas a media puder, a media entra e o `r`
    congelado fica. Mesma logica celula-a-celula do fouls_calibration.
    """
    congeladas = _congeladas()
    diagnostico = {"origem": "congeladas", "atuacoes": 0, "trocadas": [],
                   "variancia_sobre_media": None, "erro": None}
    try:
        atuacoes = carregar_atuacoes(cur)
        diagnostico["atuacoes"] = len(atuacoes)
        if len(atuacoes) < min_atuacoes:
            return congeladas, diagnostico

        medida = medir(atuacoes)
        if not medida:
            return congeladas, diagnostico

        constantes = dict(congeladas)
        for chave in congeladas:
            novo = medida.get(chave)
            if novo is None:
                continue
            constantes[chave] = round(novo, 4)
            if abs(novo - congeladas[chave]) >= 0.01:
                diagnostico["trocadas"].append(
                    f"{chave}: {congeladas[chave]} -> {round(novo, 4)}")

        diagnostico["origem"] = "recalibradas"
        diagnostico["variancia_sobre_media"] = (
            round(medida["variancia_sobre_media"], 3)
            if medida["variancia_sobre_media"] else None)
        return constantes, diagnostico
    except Exception as e:
        diagnostico["erro"] = str(e)
        return congeladas, diagnostico
