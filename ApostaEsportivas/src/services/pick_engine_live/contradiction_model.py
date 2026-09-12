"""Contradicao: quando as fontes do motor contam historias diferentes.

A REGRA DE PRODUTO QUE ISTO IMPLEMENTA
--------------------------------------
"Historico define o contexto. LIVE mostra o estado atual. LIVE ajusta o
historico. Contradicao reduz confianca." O corolario que faltava no motor:
quando as duas se contradizem FORTE, a resposta certa nao e' escolher um lado
-- e' NO_PICK.

O QUE O MOTOR JA' TINHA, E POR QUE NAO BASTAVA
----------------------------------------------
`signal_score.convergencia` ja' conta sinais a favor e contra, e `_gates` ja'
reprova quando `contra > a_favor`. Isso cobre a briga entre sinais AO VIVO --
ritmo contra tendencia, pressao contra janela. Nao cobre:

  · historico contra ao vivo · o baseline do confronto aponta para um lado da
    linha e a projecao residual aponta para o outro. Nenhum dos dois e'
    "sinal ao vivo", entao a contagem de convergencia nunca via essa briga.

  · os dois lados do confronto discordando entre si · mandante em casa com
    7.2 escanteios e visitante fora com 12.9 produzem uma media de 10.0 que
    nao descreve nem um nem outro, e ela chega no modelo como se fosse um
    numero so'.

  · regime contra direcao · jogo que criou muito e converteu pouco projetando
    Under (ver regime_model.DIRECAO_CONTRA_O_REGIME).

  · modelo contra mercado · a divergencia real, ja' medida e gravada em
    `confidence_breakdown.divergencia_modelo` desde 05/09 -- e que ate' hoje
    nao ENTRAVA em decisao nenhuma, por um motivo explicito: corrigir o termo A
    da confianca sozinho derrubava 6 dos 7 picks abaixo do piso. Aqui ela entra
    por uma porta NOVA, com limiar proprio e alto (0.25), entao ela nao mexe no
    piso de confianca nem no que ja' estava calibrado contra ele.

COMO O SCORE E' MONTADO
-----------------------
Cada fonte produz uma contradicao em [0,1] com um motivo nomeado. O score
final e' o MAIOR delas, somado a um quarto das outras:

    score = max + 0.25 * (soma das demais), truncado em 1.0

Nao e' media: quatro contradicoes fracas nao equivalem a uma forte, e uma
forte nao pode ser diluida por tres silencios. E nao e' soma pura: sinais
correlacionados (regime e mercado costumam discordar juntos) empilhariam o
mesmo fenomeno ate' 1.0 sozinhos.
"""
from __future__ import annotations

from services.pick_engine_live import regime_model

#: Divergencia contra o mercado (em pontos de probabilidade, ANTES do
#: encolhimento) a partir da qual ela conta como contradicao. 0.25 e' alto de
#: proposito: o objetivo aqui nao e' punir desacordo -- e' pegar o caso em que
#: o modelo esta' vendo outra partida. Ver o cabecalho.
DIVERGENCIA_SUSPEITA = 0.25
DIVERGENCIA_SATURA = 0.45

#: Alinhamento historico abaixo disto e' o historico apontando contra o pick.
#: 0.50 e' o ponto neutro da escala (historico exatamente na linha).
ALINHAMENTO_CONTRA = 0.42

#: Quanto os dois lados do confronto podem discordar antes de a media deles
#: deixar de descrever a partida. 0.35 = um lado 35% acima do outro.
DESACORDO_DOS_LADOS = 0.35


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _historico_contra(alinhamento: dict | None) -> tuple[float, str | None]:
    if not alinhamento or not alinhamento.get("disponivel"):
        return 0.0, None
    valor = alinhamento.get("alinhamento")
    if valor is None or valor >= ALINHAMENTO_CONTRA:
        return 0.0, None
    # 0.42 -> 0.0 ; 0.10 -> 1.0
    forca = _clamp((ALINHAMENTO_CONTRA - valor) / 0.32)
    return forca, (
        f"historico do confronto aponta contra ({alinhamento['rotulo']}, "
        f"{alinhamento['baseline_historico']} contra a linha {alinhamento['linha']})")


def _lados_discordam(alinhamento: dict | None) -> tuple[float, str | None]:
    if not alinhamento or not alinhamento.get("disponivel"):
        return 0.0, None
    casa, fora = alinhamento.get("lado_casa"), alinhamento.get("lado_fora")
    if casa is None or fora is None or min(casa, fora) <= 0:
        return 0.0, None
    if alinhamento.get("lados_concordam"):
        return 0.0, None
    desacordo = abs(casa - fora) / max(casa, fora)
    if desacordo < DESACORDO_DOS_LADOS:
        return 0.0, None
    forca = _clamp((desacordo - DESACORDO_DOS_LADOS) / 0.35)
    return forca, (
        f"os dois lados do confronto discordam ({casa:.1f} em casa contra "
        f"{fora:.1f} fora, com a linha em {alinhamento['linha']}): a media "
        f"nao descreve nenhum dos dois")


def _historico_contra_projecao(alinhamento: dict | None, projecao: float | None,
                               linha: float, direcao: str) -> tuple[float, str | None]:
    """Historico e projecao ao vivo em lados OPOSTOS da linha.

    Este e' o caso do enunciado: historico forte de Over, ao vivo parecendo
    Under (ou o contrario). Nao importa de que lado o pick esta' -- importa que
    as duas fontes discordam, porque entao uma delas esta' errada e o motor nao
    sabe qual.
    """
    if not alinhamento or not alinhamento.get("disponivel") or projecao is None:
        return 0.0, None
    hist = alinhamento.get("baseline_historico")
    if hist is None:
        return 0.0, None
    lado_hist = 1 if hist > linha else -1
    lado_live = 1 if projecao > linha else -1
    if lado_hist == lado_live:
        return 0.0, None
    # Forca pela distancia dos dois ate' a linha, normalizada pelo desvio da
    # familia (que o alinhamento ja' calculou).
    desvio = alinhamento.get("desvio_padrao") or 1.0
    distancia = (abs(hist - linha) + abs(projecao - linha)) / max(0.3, desvio)
    forca = _clamp(distancia / 1.2)
    return forca, (
        f"historico ({hist:.1f}) e projecao ao vivo ({projecao:.1f}) caem em "
        f"lados opostos da linha {linha}")


def _regime_contra(regime: dict | None, direcao: str) -> tuple[float, str | None]:
    if not regime:
        return 0.0, None
    chave = (regime.get("estado"), (direcao or "").lower())
    motivo = regime_model.DIRECAO_CONTRA_O_REGIME.get(chave)
    if not motivo:
        return 0.0, None
    # Pesada pela confianca do proprio rotulo: regime declarado com 1 de 3
    # insumos nao pode derrubar um pick como se fosse leitura completa.
    return _clamp(float(regime.get("confianca") or 0.0)), motivo


def _mercado_contra(divergencia_modelo: float | None) -> tuple[float, str | None]:
    if divergencia_modelo is None or divergencia_modelo < DIVERGENCIA_SUSPEITA:
        return 0.0, None
    forca = _clamp((divergencia_modelo - DIVERGENCIA_SUSPEITA)
                   / (DIVERGENCIA_SATURA - DIVERGENCIA_SUSPEITA))
    return forca, (
        f"o modelo discorda do mercado em {divergencia_modelo:.0%} antes do "
        f"encolhimento: ao vivo, divergencia assim costuma ser folha atrasada, "
        f"nao valor encontrado")


def _sinais_contra(conv: dict | None) -> tuple[float, str | None]:
    if not conv:
        return 0.0, None
    a_favor, contra = conv.get("a_favor") or 0, conv.get("contra") or 0
    if contra == 0:
        return 0.0, None
    forca = _clamp(contra / max(1, a_favor + contra))
    return forca, f"{contra} sinal(is) ao vivo apontam contra e {a_favor} a favor"


def contradicao(alinhamento: dict | None, projecao: float | None, linha: float,
                direcao: str, regime: dict | None, conv: dict | None,
                divergencia_modelo: float | None = None) -> dict:
    """O score de contradicao com cada fonte nomeada e medida."""
    fontes = [
        ("historico_contra_o_pick", *_historico_contra(alinhamento)),
        ("lados_discordam", *_lados_discordam(alinhamento)),
        ("historico_contra_projecao",
         *_historico_contra_projecao(alinhamento, projecao, linha, direcao)),
        ("regime_contra_direcao", *_regime_contra(regime, direcao)),
        ("modelo_contra_mercado", *_mercado_contra(divergencia_modelo)),
        ("sinais_ao_vivo_contra", *_sinais_contra(conv)),
    ]
    ativas = [(nome, forca, motivo) for nome, forca, motivo in fontes if forca > 0]
    if not ativas:
        return {"score": 0.0, "reasons": [], "fontes": [
            {"fonte": nome, "forca": 0.0} for nome, _, _ in fontes]}

    forcas = sorted((f for _, f, _ in ativas), reverse=True)
    score = _clamp(forcas[0] + 0.25 * sum(forcas[1:]))
    return {
        "score": round(score, 4),
        "reasons": [motivo for _, _, motivo in ativas],
        "fontes": [{"fonte": nome, "forca": round(forca, 4), "motivo": motivo}
                   for nome, forca, motivo in ativas],
        "dominante": ativas[0][0] if len(ativas) == 1 else max(
            ativas, key=lambda t: t[1])[0],
    }
