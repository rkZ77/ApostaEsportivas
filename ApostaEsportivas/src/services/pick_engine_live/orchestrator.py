"""Decisao do Motor Live: da folha de estatistica ao candidato aprovado.

TRES ETAPAS, E A ORDEM E' ECONOMIA
----------------------------------
    analisar(estado, ...)        sem custo de API -- pressao, ritmo, projecao
    triagem(analise)             sem custo de API -- vale consultar a odd?
    avaliar(analise, cotacoes)   so' pra quem passou na triagem

A triagem existe porque a chamada de odds ao vivo e' o item mais caro do
orcamento (1 requisicao por partida) e a maioria das partidas nao tem
oportunidade nenhuma. Perguntar "este jogo esta' se comportando de forma
diferente do esperado?" NAO custa requisicao: a resposta sai do que ja foi
lido em /fixtures/statistics.

O QUE A TRIAGEM NAO E'
----------------------
Nao e' um gate de qualidade do pick. Passar na triagem so' significa "vale a
pena olhar o preco". Quem aprova pick e' `avaliar`, com odd na mao, EV
calculado e todos os gates aplicados.
"""
from __future__ import annotations

from services.pick_engine import market_model
from services.pick_engine_live import (
    live_state, pressure_model, residual_model as rm, rhythm_model as rit,
    signal_score,
)
from services.pick_engine_live.config import (
    DEFAULT_LIVE_CONFIG, ENGINE_VERSION, LiveEngineConfig,
)

#: Quanto a projecao precisa se afastar do esperado pra valer o preco de uma
#: consulta de odd. 12% e' folgado de proposito na V1: melhor gastar uma
#: requisicao a mais e medir o falso positivo do que cortar cedo e nunca
#: descobrir onde o motor teria acertado.
DESVIO_MINIMO_TRIAGEM = 0.12


def observado_da_familia(estado: dict, familia: str) -> int | None:
    """Quanto a partida ja produziu daquela familia. None = provedor ainda
    nao publicou, e nesse caso a familia inteira sai da analise -- ausencia
    nunca vira zero (invariante 1 de services/settlement.py)."""
    if familia == "corners":
        return estado.get("corners_total")
    if familia == "goals":
        return estado.get("goals_total")
    return None


def _dados_completos(estado: dict, familia: str) -> bool:
    return observado_da_familia(estado, familia) is not None


# ─────────────────────────────────────────────────────────────────────────
# 1 · ANALISE (custo zero de API)
# ─────────────────────────────────────────────────────────────────────────
def analisar(estado: dict, observacoes: list, config: LiveEngineConfig = DEFAULT_LIVE_CONFIG,
             baselines: dict | None = None, eventos: dict | None = None,
             fresh: dict | None = None) -> dict:
    """Le a partida inteira: pressao, ritmo, tendencia, janelas e projecao por
    familia. Nenhuma chamada de API acontece aqui.

    `observacoes` sao as leituras anteriores desta mesma partida, mais recente
    primeiro (tabela live_match_observations). Sao elas que produzem janela e
    tendencia -- /fixtures/statistics so' devolve acumulado, entao sem duas
    leituras nao existe "ultimos 10 minutos".
    """
    baselines = baselines or {}
    minuto = estado.get("minuto")
    fresh = fresh or live_state.freshness(estado, observacoes, config)

    pressao = pressure_model.pressao(
        estado.get("_folha_home") or {}, estado.get("_folha_away") or {},
        int(minuto or 0), config)
    ritmo = rit.ritmo(estado, int(minuto or 0))

    familias: dict = {}
    for familia in config.familias:
        observado = observado_da_familia(estado, familia)
        if observado is None or minuto is None:
            familias[familia] = {
                "disponivel": False,
                "motivo": "estatistica nao publicada pelo provedor",
            }
            continue

        baseline = baselines.get(familia) or rm.BASELINE_PADRAO.get(familia)
        taxa = rm.taxa_por_minuto(observado, int(minuto), baseline)
        janelas = rit.janelas_recentes(observacoes, familia, int(minuto), observado, config)
        tendencia = rit.tendencia(observacoes, familia, int(minuto), observado, config)
        fator_ritmo = rit.fator_de_ritmo(
            janelas, tendencia, taxa["taxa_estimada_min"] if taxa else None, config)
        ajuste = rm.ajuste_estado(familia, estado, pressao, eventos)
        lam = rm.lambda_residual(
            familia=familia, observado=observado, minuto=int(minuto),
            status=estado.get("status") or "", baseline_por_partida=baseline,
            fator_ritmo=fator_ritmo, ajuste=ajuste)

        familias[familia] = {
            "disponivel": lam is not None,
            "observado": observado,
            "baseline": round(baseline, 2) if baseline else None,
            "baseline_origem": "liga" if baselines.get(familia) else "padrao",
            "taxa": taxa,
            "janelas": janelas,
            "tendencia": tendencia,
            "fator_ritmo": fator_ritmo,
            "ajuste_estado": ajuste,
            "lambda": lam,
            "projecao_total": lam["projecao_total"] if lam else None,
            "motivo": None if lam else "sem lambda calculavel (tempo restante ou taxa ausente)",
        }

    return {
        "estado": estado,
        "freshness": fresh,
        "pressao": pressao,
        "ritmo": ritmo,
        "eventos": eventos or {},
        "familias": familias,
        "engine_version": ENGINE_VERSION,
    }


# ─────────────────────────────────────────────────────────────────────────
# 2 · TRIAGEM (custo zero de API)
# ─────────────────────────────────────────────────────────────────────────
def triagem(analise: dict, config: LiveEngineConfig = DEFAULT_LIVE_CONFIG) -> dict:
    """Vale gastar uma requisicao de odd nesta partida?"""
    estado = analise["estado"]
    minuto = estado.get("minuto")
    status = estado.get("status") or ""
    fresh = analise.get("freshness") or {}

    if status not in ("1H", "2H", "HT"):
        return {"vale": False, "motivo": f"status fora da janela util ({status})", "familias": []}
    if minuto is None:
        return {"vale": False, "motivo": "sem minuto publicado", "familias": []}
    if int(minuto) < config.minuto_inicial:
        return {"vale": False, "motivo": f"minuto {minuto}' antes da janela ({config.minuto_inicial}')", "familias": []}
    if int(minuto) > config.minuto_final:
        return {"vale": False, "motivo": f"minuto {minuto}' depois da janela ({config.minuto_final}')", "familias": []}
    if int(minuto) < config.minutos_minimos_observados:
        return {"vale": False, "motivo": "amostra do proprio jogo curta demais", "familias": []}

    # Dado velho bloqueia ANTES de qualquer modelo. Ao vivo, decidir sobre um
    # estado que ja mudou nao produz um pick impreciso -- produz um pick sobre
    # outra partida.
    if fresh.get("nivel") == live_state.STALE:
        return {"vale": False, "familias": [],
                "motivo": f"dado STALE: {'; '.join(fresh.get('motivos') or []) or 'feed atrasado'}"}
    if fresh.get("nivel") == live_state.UNKNOWN:
        return {"vale": False, "familias": [],
                "motivo": "qualidade do dado desconhecida"}

    candidatas, detalhes = [], []
    for familia, info in (analise.get("familias") or {}).items():
        if not info.get("disponivel"):
            detalhes.append({"familia": familia, "vale": False,
                             "motivo": info.get("motivo")})
            continue
        baseline = info["baseline"]
        projecao = info["projecao_total"]
        desvio = (projecao - baseline) / baseline if baseline else 0.0
        vale = abs(desvio) >= DESVIO_MINIMO_TRIAGEM
        detalhes.append({
            "familia": familia, "vale": vale, "observado": info["observado"],
            "projecao_total": projecao, "baseline": baseline,
            "desvio": round(desvio, 4),
            "lambda_residual": info["lambda"]["lambda_residual"],
            "motivo": None if vale else f"projecao {projecao:.1f} colada no esperado {baseline:.1f}",
        })
        if vale:
            candidatas.append(familia)

    return {
        "vale": bool(candidatas),
        "motivo": None if candidatas else "nenhuma familia se afastou do esperado",
        "familias": candidatas,
        "detalhes": detalhes,
    }


# ─────────────────────────────────────────────────────────────────────────
# 3 · AVALIACAO (com a odd na mao)
# ─────────────────────────────────────────────────────────────────────────
def avaliar(analise: dict, cotacoes: list, config: LiveEngineConfig = DEFAULT_LIVE_CONFIG) -> list[dict]:
    """Candidatos com probabilidade, edge, EV, convergencia, confianca e o
    veredito dos gates.

    Devolve TODOS os avaliados, aprovados e reprovados, cada um com `aprovado`
    e `motivos_reprovacao`. Quem escolhe e' `melhor_candidato`. Separar as duas
    coisas e' o que permite o log dizer "avaliei 8 mercados, aprovei 1" em vez
    de so' mostrar o vencedor.
    """
    estado = analise["estado"]
    minuto = int(estado.get("minuto") or 0)
    avaliados: list[dict] = []

    for entrada in cotacoes:
        familia = entrada["familia"]
        info = (analise.get("familias") or {}).get(familia)
        if not info or not info.get("disponivel"):
            continue
        observado = info["observado"]
        lam_info = info["lambda"]

        linha, direcao, odd = entrada["linha"], entrada["direcao"], entrada["odd"]
        prob_modelo = rm.probabilidade_da_linha(
            lam_info["lambda_residual"], linha, direcao, observado)
        if prob_modelo is None:
            continue

        encolhido = rm.encolher_contra_mercado(prob_modelo, entrada["prob_mercado"], minuto)
        prob = encolhido["prob"]

        baseline_mercado = entrada["prob_mercado"]
        if baseline_mercado is None:
            baseline_mercado = market_model.implied_prob(odd)
        valor = market_model.edge_and_ev(prob, odd, baseline_mercado)

        conv = signal_score.convergencia(
            direcao=direcao, familia=familia, estado=estado,
            pressao=analise.get("pressao"), ritmo=analise.get("ritmo"),
            tendencia=info.get("tendencia"), janelas=info.get("janelas"),
            taxa_estimada_min=(info.get("taxa") or {}).get("taxa_estimada_min"),
            eventos=analise.get("eventos"), config=config)

        # Folga entre a projecao e a linha, no sentido do pick. Projecao colada
        # na linha e' moeda ao ar mesmo com EV positivo: meio evento decide.
        distancia = (info["projecao_total"] - linha if direcao == "over"
                     else linha - info["projecao_total"])

        conf = signal_score.live_confidence(
            prob_final=prob, prob_mercado=entrada["prob_mercado"], minuto=minuto,
            conv=conv, fresh=analise.get("freshness"), distancia_da_linha=distancia)

        motivos = _gates(entrada, prob, valor, conf, conv, observado, linha, direcao,
                         analise.get("freshness"), config)
        avaliados.append({
            **entrada,
            "observado_na_criacao": observado,
            "prob_modelo_puro": encolhido["prob_pre_encolhimento"],
            "peso_modelo": encolhido["peso_modelo"],
            "probability": prob,
            "edge": valor["edge"],
            "ev": valor["ev"],
            "confidence": conf["confidence"],
            "live_signal_score": conv.get("score"),
            "projecao_total": info["projecao_total"],
            "distancia_da_linha": round(distancia, 3),
            "engine_version": ENGINE_VERSION,
            "aprovado": not motivos,
            "motivos_reprovacao": motivos,
            "debug": {
                "lambda": lam_info,
                "taxa": info.get("taxa"),
                "janelas": info.get("janelas"),
                "tendencia": info.get("tendencia"),
                "fator_ritmo": info.get("fator_ritmo"),
                "ajuste_estado": info.get("ajuste_estado"),
                "convergencia": conv,
                "confianca": conf,
                "encolhimento": encolhido,
                "faltam_para_a_linha": round(linha - observado, 2),
                "intervalo_restante_80": rm.intervalo_poisson(lam_info["lambda_residual"]),
                "prob_mercado": entrada["prob_mercado"],
                "origem_prob_mercado": entrada["origem_prob_mercado"],
            },
        })

    avaliados.sort(key=lambda c: (not c["aprovado"], -c["ev"]))
    return avaliados


def _gates(entrada: dict, prob: float, valor: dict, conf: dict, conv: dict,
           observado: int, linha: float, direcao: str, fresh: dict | None,
           config: LiveEngineConfig = DEFAULT_LIVE_CONFIG) -> list[str]:
    """Todos os motivos de reprovacao, nao o primeiro.

    Sem short-circuit de proposito: saber que um candidato reprovou por EV E
    por convergencia e' informacao diferente de saber que reprovou so' por EV,
    e e' isso que orienta qual limiar ajustar depois.
    """
    motivos: list[str] = []

    # Linha ja resolvida pelo placar atual. Um "Over 8.5 escanteios" com 9 no
    # placar nao e' uma aposta -- e' dinheiro parado esperando o apito, e a
    # casa so' cota isso enquanto nao atualiza. Publicar seria vender certeza
    # que ja acabou.
    if direcao == "over" and observado > linha:
        motivos.append("linha ja batida pelo placar atual")
    if direcao == "under" and observado > linha:
        motivos.append("linha ja perdida pelo placar atual")

    if (fresh or {}).get("nivel") == live_state.STALE:
        motivos.append("dado STALE: o estado lido ja mudou")

    if valor["ev"] < config.ev_minimo:
        motivos.append(f"EV {valor['ev']:+.1%} abaixo do minimo ({config.ev_minimo:+.1%})")
    if conf["confidence"] < config.confianca_minima:
        motivos.append(f"confianca {conf['confidence']:.0%} abaixo do minimo ({config.confianca_minima:.0%})")
    if entrada["odd"] < config.odd_minima:
        motivos.append(f"odd {entrada['odd']} abaixo do minimo ({config.odd_minima})")
    if entrada["odd"] > config.odd_maxima:
        motivos.append(f"odd {entrada['odd']} acima do teto ({config.odd_maxima})")

    # Sinais brigando entre si. Um Over com ritmo alto mas tendencia
    # desacelerando nao e' um Over sustentado -- e' um Over que ja aconteceu.
    if conv.get("contra", 0) > conv.get("a_favor", 0):
        motivos.append(
            f"sinais contraditorios ({conv['contra']} contra, {conv['a_favor']} a favor)")
    elif conv.get("a_favor", 0) < config.sinais_minimos_convergentes:
        motivos.append(
            f"convergencia fraca ({conv.get('a_favor', 0)} sinais, "
            f"minimo {config.sinais_minimos_convergentes})")

    # Linha cotada de um lado so' nao tem no-vig, entao o baseline do edge e'
    # a odd crua, com a margem da casa embutida -- o edge sai inflado por
    # construcao. Ao vivo isso e' pior que no pre-jogo, onde da' pra comparar
    # com varias casas.
    if not entrada.get("tem_par"):
        motivos.append("linha sem o lado contrario cotado (sem no-vig)")

    return motivos


def melhor_candidato(avaliados: list[dict]) -> dict | None:
    """O aprovado de maior EV. Empate desempata por confianca.

    O pre-jogo separa "qual mercado vence" (so' estatistica) de "qual linha
    vence" (com odd). Aqui essa separacao nao se aplica: com duas familias e um
    mercado ja' repreçado pelo minuto, nao ha disputa entre familias pra
    arbitrar -- ha uma pergunta so', que e' onde o preco esta' mais atrasado em
    relacao ao jogo. Se a V2 abrir cartoes, chutes e faltas, essa decisao volta
    a valer a pena e deve ser revisitada.
    """
    aprovados = [c for c in avaliados if c["aprovado"]]
    if not aprovados:
        return None
    return max(aprovados, key=lambda c: (c["ev"], c["confidence"]))
