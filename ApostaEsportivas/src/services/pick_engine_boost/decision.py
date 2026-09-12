"""As portas e o score final -- onde o Pick Boost decide PICK ou NO_PICK.

A INVERSAO QUE DEFINE A V2
--------------------------
Na V1 o unico caminho pra um jogo nao virar pick era falhar num corte de
quantidade: amostra abaixo do piso, odd fora da faixa, probabilidade de perna
abaixo do minimo, Score abaixo de 70. Tudo o mais -- EV, edge, risco de
primeiro tempo, distancia da projecao pra linha, desacordo entre modelo e
historico, cobertura de dado -- era calculado DEPOIS da aprovacao e gravado
como informacao. Um numero que nao reprova nao e' um criterio, e' um enfeite.

Aqui NO_PICK e' uma resposta, com codigo proprio, e o motor prefere nao
apostar. Nove portas, todas com motivo nomeado:

    1  EV > 0                     6  projecao com folga contra a linha
    2  edge > 0                   7  sem contradicao grave
    3  qualidade de dado          8  probabilidade calibrada
    4  amostra minima             9  modelo e historico nao divergem demais
    5  risco de HT sob o teto

SCORE FINAL x SCORE ESTATISTICO
-------------------------------
O Score Estatistico (score.py) continua existindo e continua significando a
mesma coisa: quao forte e' o jogo pra esta combinacao. O Score Final o
envolve, junto de modelo, mando, seguranca de HT, amostra, qualidade de dado e
convergencia -- e desconta as penalidades das zonas cinzentas (risco de HT
entre 65 e 80, margem apertada, divergencia entre 10 e 18 pontos).

O PRECO NAO ENTRA NO SCORE FINAL. Ele elimina na porta 1 e na porta 2, e o
peso dele na ordenacao e' zero (cfg.PESOS_SCORE_FINAL["valor"]). Um jogo fraco
bem pago nao pode subir no ranking -- isso e' o defeito oposto ao que a V2 veio
corrigir, e ja' e' regra escrita do projeto.
"""
from __future__ import annotations

from services.pick_engine_boost import config as cfg

# -- Codigos de NO_PICK ------------------------------------------------------
NO_PICK_NEGATIVE_EV = "NO_PICK_NEGATIVE_EV"
NO_PICK_NEGATIVE_EDGE = "NO_PICK_NEGATIVE_EDGE"
NO_PICK_SMALL_SAMPLE = "NO_PICK_SMALL_SAMPLE"
NO_PICK_LOW_DATA_QUALITY = "NO_PICK_LOW_DATA_QUALITY"
NO_PICK_HIGH_HT_RISK = "NO_PICK_HIGH_HT_RISK"
NO_PICK_HIGH_TAIL_RISK = "NO_PICK_HIGH_TAIL_RISK"
NO_PICK_LOW_PROJECTION_MARGIN = "NO_PICK_LOW_PROJECTION_MARGIN"
NO_PICK_MODEL_CONTRADICTION = "NO_PICK_MODEL_CONTRADICTION"
NO_PICK_LOW_CALIBRATION = "NO_PICK_LOW_CALIBRATION"
NO_PICK_INSUFFICIENT_CONVERGENCE = "NO_PICK_INSUFFICIENT_CONVERGENCE"
NO_PICK_LOW_SCORE = "NO_PICK_LOW_SCORE"

#: Frase curta por codigo. Estavel de proposito: vira GROUP BY no painel de
#: auditoria, mesma regra das constantes MOTIVO_* do decision_log.
MOTIVOS = {
    NO_PICK_NEGATIVE_EV: "EV não positivo na odd oferecida",
    NO_PICK_NEGATIVE_EDGE: "sem vantagem sobre a probabilidade implícita",
    NO_PICK_SMALL_SAMPLE: "amostra insuficiente para afirmar",
    NO_PICK_LOW_DATA_QUALITY: "qualidade de dado insuficiente",
    NO_PICK_HIGH_HT_RISK: "risco de gols no primeiro tempo",
    NO_PICK_HIGH_TAIL_RISK: "cauda perigosa no primeiro tempo",
    NO_PICK_LOW_PROJECTION_MARGIN: "projeção sem folga contra a linha",
    NO_PICK_MODEL_CONTRADICTION: "contradição entre modelo e histórico",
    NO_PICK_LOW_CALIBRATION: "probabilidade fora da faixa calibrada",
    NO_PICK_INSUFFICIENT_CONVERGENCE: "poucos indicadores sustentam a pick",
    NO_PICK_LOW_SCORE: "score final abaixo do mínimo",
}


def _faixa(valor, piso: float, teto: float) -> float:
    if valor is None or teto == piso:
        return 0.0
    return max(0.0, min(1.0, (float(valor) - piso) / (teto - piso)))


# ---------------------------------------------------------------------------
# Os scores separados (STATISTICAL / MODEL / VALUE / RISK / DATA QUALITY)
# ---------------------------------------------------------------------------
def scores(confronto: dict, score_estatistico: float, risco_ht: dict,
           qualidade: dict, convergencia: dict, perfil_home: dict,
           perfil_away: dict, ev: float | None) -> dict:
    """Cada dimensao na sua propria escala 0-100, sem se compensarem.

    Separados porque o pedido e' explicito e a razao e' boa: enquanto forem um
    numero so', um Score alto de estatistica podia carregar um EV negativo pra
    dentro. Aqui o valor tem escala propria, e a porta dele e' outra.
    """
    modelo = [
        _faixa(confronto.get("prob_modelo_ft"), 0.70, 0.93),
        _faixa(confronto.get("prob_modelo_ht"), 0.80, 0.97),
        _faixa(confronto.get("margem_ft"), *cfg.FAIXA_MARGEM_FT),
        _faixa(confronto.get("margem_ht"), *cfg.FAIXA_MARGEM_HT),
    ]
    mando = [p.get("freq_over15_mando") for p in (perfil_home, perfil_away)]
    mando = [float(m) for m in mando if m is not None]
    amostras = [(confronto.get("consistencia") or {}).get("min_amostra_ft"),
                (confronto.get("consistencia") or {}).get("min_amostra_ht")]

    return {
        "estatistico": round(float(score_estatistico), 1),
        "modelo": round(sum(modelo) / len(modelo) * 100, 1),
        "valor": round(_faixa(ev, 0.0, 0.15) * 100, 1),
        "mando": round(_faixa(sum(mando) / len(mando) if mando else None, 0.60, 0.95) * 100, 1),
        "seguranca_ht": round(100 - (risco_ht.get("score") or 0), 1),
        "amostra": round((_faixa(amostras[0], cfg.MIN_JOGOS_FT, cfg.JANELA_LONGA) * 0.5
                          + _faixa(amostras[1], cfg.MIN_JOGOS_HT, cfg.JANELA_LONGA) * 0.5) * 100, 1),
        "qualidade_dado": round(qualidade.get("score") or 0.0, 1),
        "convergencia": round((convergencia.get("fracao") or 0.0) * 100, 1),
    }


def penalidades(risco_ht: dict, confronto: dict, edge: float | None) -> dict:
    """As zonas cinzentas: o que nao bloqueia mas tem que doer.

    Existem porque um limiar duro sozinho produz o degrau absurdo -- risco 79
    valendo tanto quanto risco 20 e risco 80 valendo NO_PICK. Entre o ponto em
    que o problema comeca e o ponto em que ele bloqueia, o preco sobe junto.
    """
    itens = {}

    risco = risco_ht.get("score") or 0
    if risco >= cfg.HT_RISK_PENALIZA:
        fatia = _faixa(risco, cfg.HT_RISK_PENALIZA, cfg.HT_RISK_BLOQUEIA)
        itens["risco_ht"] = round(fatia * cfg.PENALIDADE_MAX_HT_RISK, 2)

    margem_ft = confronto.get("margem_ft")
    if margem_ft is not None and float(margem_ft) < cfg.FAIXA_MARGEM_FT[1]:
        falta = 1 - _faixa(margem_ft, cfg.MARGEM_MIN_FT, cfg.FAIXA_MARGEM_FT[1])
        itens["margem_ft"] = round(falta * cfg.PENALIDADE_MAX_MARGEM * 0.5, 2)
    lam_ht = confronto.get("lambda_ht")
    if lam_ht is not None and float(lam_ht) >= cfg.LAMBDA_HT_PENALIZA:
        fatia = _faixa(lam_ht, cfg.LAMBDA_HT_PENALIZA, cfg.LAMBDA_HT_BLOQUEIA)
        itens["projecao_ht"] = round(fatia * cfg.PENALIDADE_MAX_MARGEM, 2)

    div = confronto.get("divergencia_modelo_historico")
    if div is not None and abs(float(div)) >= cfg.DIVERGENCIA_PENALIZA:
        fatia = _faixa(abs(float(div)), cfg.DIVERGENCIA_PENALIZA, cfg.DIVERGENCIA_MAX)
        itens["divergencia"] = round(fatia * cfg.PENALIDADE_MAX_DIVERGENCIA, 2)

    if edge is not None and float(edge) < cfg.EDGE_BAIXO:
        falta = 1 - _faixa(edge, 0.0, cfg.EDGE_BAIXO)
        itens["edge_baixo"] = round(falta * 5.0, 2)

    itens["total"] = round(sum(v for k, v in itens.items() if k != "total"), 2)
    return itens


def score_final(dimensoes: dict, punicoes: dict) -> float:
    """Media ponderada das dimensoes, menos as penalidades.

    Os pesos sao normalizados pela soma, entao zerar `valor` nao encolhe o
    score -- ele redistribui.
    """
    pesos = cfg.PESOS_SCORE_FINAL
    soma_pesos = sum(pesos.values()) or 1.0
    bruto = sum(dimensoes.get(k, 0.0) * p for k, p in pesos.items()) / soma_pesos
    return round(max(0.0, min(100.0, bruto - (punicoes.get("total") or 0.0))), 1)


# ---------------------------------------------------------------------------
# As portas
# ---------------------------------------------------------------------------
def avaliar(*, ev, edge, qualidade, convergencia, risco_ht, tail, confronto,
            contradicoes, calibrada, amostra_classe, score_final_valor) -> dict:
    """PICK ou NO_PICK, com o codigo do primeiro impedimento.

    A ORDEM IMPORTA e nao e' arbitraria: o valor vem primeiro porque e' a
    porta que a V1 nao tinha e o motivo mais barato de recusar -- nao adianta
    discutir qualidade de dado num jogo que nao paga. Depois vem o que
    invalida a leitura (dado, amostra), depois o que invalida o modelo (risco,
    projecao, contradicao) e por ultimo o corte de ordenacao.

    Todas as portas sao avaliadas mesmo depois da primeira falhar: o rastro
    precisa dizer QUANTAS falharam, nao so' qual foi a primeira.
    """
    portas = {
        "ev": ev is not None and float(ev) > cfg.EV_MINIMO,
        "edge": edge is not None and float(edge) > cfg.EDGE_MINIMO,
        "data_quality": bool(qualidade.get("suficiente")),
        # So' INSUFICIENTE reprova aqui, e a escolha e' deliberada: o piso de
        # 4 jogos e' decisao do usuario e vale igual nos cinco pipelines, entao
        # esta porta nao o levanta por conta propria. Amostra MUITO_FRACA
        # continua passando -- e continua pagando por isso tres vezes: encolhe
        # mais a frequencia (shrinkage), pontua menos na dimensao `amostra` e
        # derruba o DATA_QUALITY, que na pratica e' quem reprova um jogo de 4
        # contra 4. A diferenca e' que ali o motivo fica nomeado.
        "sample": amostra_classe != "INSUFICIENTE",
        "ht_risk": not risco_ht.get("bloqueia") and not tail.get("bloqueia"),
        "projection": (confronto.get("margem_ft") is not None
                       and float(confronto["margem_ft"]) >= cfg.MARGEM_MIN_FT
                       and confronto.get("lambda_ht") is not None
                       and float(confronto["lambda_ht"]) < cfg.LAMBDA_HT_BLOQUEIA),
        "contradiction": not contradicoes.get("bloqueia"),
        "calibration": calibrada.get("prob") is not None,
        "convergence": bool(convergencia.get("suficiente")),
        "score": score_final_valor >= cfg.SCORE_MINIMO,
    }

    ordem = [
        ("ev", NO_PICK_NEGATIVE_EV),
        ("edge", NO_PICK_NEGATIVE_EDGE),
        ("data_quality", NO_PICK_LOW_DATA_QUALITY),
        ("sample", NO_PICK_SMALL_SAMPLE),
        ("ht_risk", NO_PICK_HIGH_TAIL_RISK if tail.get("bloqueia") else NO_PICK_HIGH_HT_RISK),
        ("projection", NO_PICK_LOW_PROJECTION_MARGIN),
        ("contradiction", NO_PICK_MODEL_CONTRADICTION),
        ("calibration", NO_PICK_LOW_CALIBRATION),
        ("convergence", NO_PICK_INSUFFICIENT_CONVERGENCE),
        ("score", NO_PICK_LOW_SCORE),
    ]
    reprovadas = [codigo for chave, codigo in ordem if not portas[chave]]

    if not reprovadas:
        return {"decision": "PICK", "codigo": None, "motivo": None,
                "gates": portas, "gates_reprovados": []}
    codigo = reprovadas[0]
    return {"decision": "NO_PICK", "codigo": codigo,
            "motivo": _frase(codigo, ev=ev, edge=edge, qualidade=qualidade,
                             risco_ht=risco_ht, confronto=confronto,
                             contradicoes=contradicoes, convergencia=convergencia,
                             amostra_classe=amostra_classe,
                             score_final_valor=score_final_valor),
            "gates": portas, "gates_reprovados": reprovadas}


def _frase(codigo: str, **d) -> str:
    """Motivo legivel, com o numero que reprovou dentro.

    O prefixo e' a constante estavel (agrupavel); o parenteses e' o detalhe.
    """
    base = MOTIVOS.get(codigo, codigo)
    ev, edge = d.get("ev"), d.get("edge")
    conf = d.get("confronto") or {}
    if codigo == NO_PICK_NEGATIVE_EV and ev is not None:
        return f"{base} (EV {float(ev) * 100:+.1f}%)"
    if codigo == NO_PICK_NEGATIVE_EDGE and edge is not None:
        return f"{base} (edge {float(edge) * 100:+.1f} p.p.)"
    if codigo == NO_PICK_LOW_DATA_QUALITY:
        q = d.get("qualidade") or {}
        return f"{base} ({q.get('score')} · {q.get('classe')})"
    if codigo == NO_PICK_SMALL_SAMPLE:
        return f"{base} ({d.get('amostra_classe')})"
    if codigo in (NO_PICK_HIGH_HT_RISK, NO_PICK_HIGH_TAIL_RISK):
        r = d.get("risco_ht") or {}
        return f"{base} (HT risk {r.get('score')} · {r.get('classe')})"
    if codigo == NO_PICK_LOW_PROJECTION_MARGIN:
        return (f"{base} (projeta {conf.get('lambda_ft')} gol no jogo e "
                f"{conf.get('lambda_ht')} no intervalo)")
    if codigo == NO_PICK_MODEL_CONTRADICTION:
        graves = (d.get("contradicoes") or {}).get("graves") or []
        detalhe = graves[0]["descricao"] if graves else "modelo e histórico discordam"
        return f"{base}: {detalhe}"
    if codigo == NO_PICK_INSUFFICIENT_CONVERGENCE:
        c = d.get("convergencia") or {}
        return f"{base} ({c.get('a_favor')} de {c.get('disponiveis')} indicadores)"
    if codigo == NO_PICK_LOW_SCORE:
        return f"{base} (score {d.get('score_final_valor')} < {cfg.SCORE_MINIMO})"
    return base
