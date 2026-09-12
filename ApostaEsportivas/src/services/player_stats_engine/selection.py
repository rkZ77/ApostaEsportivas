"""Escolha entre candidatos aprovados (§38, §39) e tamanho da aposta (§40).

O PRECO NAO ORDENA. PESO ZERO, NAO PESO BAIXO
---------------------------------------------
Ate' aqui o Player Stats ordenava por `market_pick_score.pick_score`, que da'
0.28 pra um termo de seguranca da ODD e 0.10 pro EDGE -- 38% da escolha era
preco. Essa regra ja' tinha sido corrigida duas vezes no projeto, nos dois
motores, e com a mesma frase: odd e EV ELIMINAM (faixa de odd, piso de edge, nos
gates) e nunca ORDENAM. O pre-jogo generico nao foi de 100% pra 30%, foi pra
zero; o ao vivo tirou os 30% dele em 05/09. Este pipeline ficou de fora das duas
passagens porque usa um Score proprio.

`pick_score` continua existindo e continua sendo gravado -- ele e' comparavel
com o dos outros pipelines de mercado proprio e serve de referencia historica.
O que ele nao faz mais e' DECIDIR qual pick sai.

§38 E' LITERALMENTE ISTO
------------------------
"Jogador A EV +20% risco alto, Jogador B EV +13% risco baixo -- B pode ser
superior." Com um score que pontua odd e edge, A ganha sempre. Aqui A perde nos
tres termos que sobraram (qualidade do dado, margem e variancia) e nao ganha em
nenhum, porque o unico lugar onde ele era melhor saiu da conta.
"""
from __future__ import annotations

# Somam 1.0. Nenhum deles e' preco -- ver o topo do modulo.
PESO_PROBABILIDADE = 0.40
PESO_AMOSTRA = 0.20
PESO_QUALIDADE = 0.20
PESO_MARGEM = 0.20

#: Margem relativa que vale o termo inteiro. 40% de folga sobre a linha ja' e'
#: uma projecao confortavel; premiar alem disso faria o motor preferir a linha
#: mais facil, que e' a de odd baixa -- preco entrando pela porta dos fundos.
MARGEM_SATURACAO = 0.40

#: Quanto cada classe de risco custa no score final. Sao subtraidos DEPOIS da
#: soma ponderada, e nao embutidos num termo, pra a auditoria poder mostrar o
#: score bruto e o abatimento em separado.
CUSTO_RISCO = {"LOW": 0.0, "MEDIUM": 0.04, "HIGH": 0.12}


def score_de_selecao(*, probabilidade: float, amostra: int | None,
                     amostra_saturacao: int, data_quality: float | None,
                     margem_relativa: float | None,
                     penalidade_variancia: float,
                     risco_minutos: str, risco_funcao: str) -> dict:
    """Valor AJUSTADO AO RISCO (§46), com a conta aberta.

    Devolve os termos junto com o total porque a pergunta que a aba Motor
    responde e' "por que este e nao aquele", e ela nao tem resposta a partir de
    um numero so'.
    """
    p = max(float(probabilidade or 0), 0.0)
    termo_amostra = (min(float(amostra or 0) / amostra_saturacao, 1.0)
                     if amostra_saturacao > 0 else 0.0)
    termo_qualidade = min(max(float(data_quality or 0) / 100, 0.0), 1.0)
    termo_margem = (min(max(float(margem_relativa or 0), 0.0) / MARGEM_SATURACAO, 1.0)
                    if margem_relativa is not None else 0.0)

    bruto = (p * PESO_PROBABILIDADE
             + termo_amostra * PESO_AMOSTRA
             + termo_qualidade * PESO_QUALIDADE
             + termo_margem * PESO_MARGEM)
    abatimento = (float(penalidade_variancia or 0)
                  + CUSTO_RISCO.get(risco_minutos, 0.0)
                  + CUSTO_RISCO.get(risco_funcao, 0.0))
    return {
        "score": round(max(bruto - abatimento, 0.0), 4),
        "bruto": round(bruto, 4),
        "abatimento": round(abatimento, 4),
        "termos": {
            "probabilidade": round(p * PESO_PROBABILIDADE, 4),
            "amostra": round(termo_amostra * PESO_AMOSTRA, 4),
            "qualidade": round(termo_qualidade * PESO_QUALIDADE, 4),
            "margem": round(termo_margem * PESO_MARGEM, 4),
        },
        "preco": 0.0,
    }


def fator_de_stake(*, data_quality: float | None, classe_amostra: str,
                   risco_minutos: str, penalidade_variancia: float) -> dict:
    """§40 -- o multiplicador do stake que NAO vem de EV.

    `staking.calculate_stake` ja' dimensiona por confianca e odd. O que faltava
    e' o outro lado: dois picks com a mesma confianca e a mesma odd nao merecem
    a mesma unidade se um deles esta' sustentado por oito atuacoes e o outro por
    vinte. Aqui o fator so' REDUZ -- nunca aumenta, porque nenhuma qualidade de
    dado torna uma prop de jogador mais generosa do que o dimensionamento padrao
    ja' permite.
    """
    fator = 1.0
    motivos = []
    if classe_amostra in ("insuficiente", "muito limitada"):
        fator *= 0.5
        motivos.append(f"amostra {classe_amostra}")
    elif classe_amostra == "limitada":
        fator *= 0.75
        motivos.append("amostra limitada")
    if (data_quality or 0) < 80:
        fator *= 0.8
        motivos.append(f"qualidade do dado {data_quality:.0f}")
    if risco_minutos == "MEDIUM":
        fator *= 0.8
        motivos.append("risco de minutos médio")
    if penalidade_variancia >= 0.05:
        fator *= 0.85
        motivos.append("dispersão acima da referência do método")
    return {"fator": round(fator, 3), "motivos": motivos}
