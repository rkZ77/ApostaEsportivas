"""Gate de contexto: barra a pick que contradiz o que a partida vai ser.

O CASO QUE ORIGINOU ESTE MODULO
-------------------------------
"Under cartoes" aprovado num Fluminense x Vasco, jogo de volta valendo
classificacao. A taxa historica vinha de 15 jogos de pontos corridos e estava
CERTA pra aquele universo. O erro nao foi de calculo, foi de universo: aquela
partida nao pertencia a distribuicao que gerou a amostra.

O MECANISMO, E POR QUE ELE E' DIRECIONAL
----------------------------------------
Time que precisa do resultado se abre. Isso nao e' folclore, e' consequencia:
quem esta atras no agregado tem que atacar, quem esta na frente recua pra
segurar, e a partida inteira desloca junto:

    escanteios   sobe   (mais volume ofensivo de um lado, mais pressao)
    chutes       sobe   (idem)
    gols         sobe   (jogo mais aberto dos dois lados)
    cartoes      sobe   (falta tatica de quem segura, frustracao de quem ataca)
    faltas       sobe   (mesmo motivo)

Todos os cinco apontam PRA CIMA. Ou seja: num jogo assim, o mercado perigoso
nao e' "cartoes", e' "UNDER de qualquer um deles". O gate antigo
(referee_model.cards_market_eligible) era cego a direcao -- bloqueava jogo
frio inteiro e liberava jogo quente inteiro, Over e Under igualmente. Era
exatamente a cegueira que deixou o Under passar.

POR QUE PENALIDADE PROPORCIONAL E NAO REGRA BINARIA
---------------------------------------------------
Um "if classico then reject" seria constante escolhida, nao quantidade
medida -- e erraria nos dois sentidos: mataria Under legitimo em classico
morno de meio de tabela e liberaria Under em decisao que o parser nao
reconheceu. Aqui a penalidade e' proporcional a dois numeros MEDIDOS:

  1. o excesso disciplinar do confronto direto (rivalry_model, do H2H real)
  2. o que esta em jogo (match_context_model.stakes_score, do agregado real)

Sem amostra de H2H e sem mata-mata detectado, o gate nao faz nada -- ausencia
de dado nunca vira evidencia de calma.
"""
from __future__ import annotations

from services.pick_engine import match_context_model, rivalry_model

# Familias cujo volume sobe quando a partida abre. Todas compartilham o mesmo
# mecanismo (mais ataque, mais desespero, mais falta tatica), entao todas
# recebem o mesmo tratamento direcional.
FAMILIAS_DIRECIONAIS = ("cards", "corners", "shots", "shots_on_target", "goals", "fouls")

# Acima deste score de "quanto esta em jogo" (match_context_model.stakes_score,
# 0.5 = jogo comum) a partida e' tratada como decisao. 0.68 exige mais que
# apenas ser mata-mata: uma ida de oitavas fica em ~0.61 e nao dispara, uma
# volta de quartas com agregado empatado passa de 0.75 e dispara.
STAKES_DECISIVO = 0.68

# Penalidade maxima de probabilidade aplicada a um Under que contradiz o
# contexto. 0.10 e' deliberadamente maior que a penalidade de variancia
# (0.10 no confidence) porque aqui o erro nao e' de precisao, e' de universo:
# a amostra descreve outro tipo de jogo.
PENALIDADE_MAX = 0.10

# Acima deste total de sinal contrario, o Under nao e' penalizado e sim
# BLOQUEADO -- ha um ponto em que reduzir a probabilidade nao basta, porque a
# estimativa inteira veio da distribuicao errada.
BLOQUEIO_LIMIAR = 0.085


def _direcao(candidate: dict) -> str:
    return (candidate.get("_direction") or candidate.get("value") or "").strip().lower()


def build_context(round_str: str | None, home_team_id: int, away_team_id: int,
                  h2h_matches: list | None, league_id, season,
                  baseline_cartoes: float | None, before_date=None) -> dict:
    """Monta o contexto completo da partida a partir do dado ja' disponivel.

    Nenhuma chamada de API nova: `round_str` vem de `fixtures.round` (ja'
    coletado) e `h2h_matches` de MatchStatsService.get_h2h_matches(), que le
    `match_statistics`.
    """
    jogo_ida = match_context_model.encontrar_jogo_de_ida(
        h2h_matches or [], league_id, season, before_date=before_date)
    tie = match_context_model.tie_context(round_str, home_team_id, away_team_id, jogo_ida)
    rivalidade = rivalry_model.rivalry_signal(h2h_matches or [], baseline_cartoes)

    return {
        "tie": tie,
        "rivalidade": rivalidade,
        "stakes": match_context_model.stakes_score(tie),
        "descricao": match_context_model.descrever(tie),
    }


def build_for_fixture(match_stats, fixture: dict, convergencia_cartoes: dict | None = None,
                      before_date=None) -> dict | None:
    """Contexto da partida a partir do servico de estatisticas e do fixture.

    Ponto de entrada unico dos pipelines -- os seis chamam daqui em vez de
    repetir a montagem, que foi como `context_model.build_context` acabou
    recebendo None de classificacao em quatro lugares diferentes por meses.

    `convergencia_cartoes`: saida de stats_model.expected_value_convergence()
    da familia 'cards'. E' a linha de base contra a qual o excesso do confronto
    direto e' medido; sem ela a rivalidade fica marcada como nao confiavel e o
    gate nao age -- ausencia de dado nunca vira evidencia de calma.

    Nunca levanta: contexto e' sinal auxiliar e nao pode derrubar a geracao de
    pick. Falha -> None -> gate inerte -> motor igual ao de antes.
    """
    try:
        h2h = match_stats.get_h2h_matches(
            fixture["home_team_id"], fixture["away_team_id"], before_date=before_date)
        baseline = (convergencia_cartoes or {}).get("expected_value")
        return build_context(
            round_str=fixture.get("round"),
            home_team_id=fixture["home_team_id"], away_team_id=fixture["away_team_id"],
            h2h_matches=h2h, league_id=fixture.get("league_id"),
            season=fixture.get("season"), baseline_cartoes=baseline,
            before_date=before_date,
        )
    except Exception as e:
        print(f"[CONTEXT_GATE] Contexto indisponivel para fixture "
              f"{fixture.get('fixture_id')}: {e}")
        return None


def pressao_contraria(candidate: dict, contexto: dict | None) -> dict:
    """Quanto o contexto contradiz a direcao deste candidato.

    Devolve o total e as parcelas separadas -- a explicacao de rejeicao precisa
    poder dizer QUAL sinal pesou, nao so' que pesou.
    """
    parcelas: list = []
    total = 0.0

    if not contexto:
        return {"total": 0.0, "parcelas": parcelas, "aplicavel": False}

    familia = candidate.get("market_type")
    if familia not in FAMILIAS_DIRECIONAIS:
        return {"total": 0.0, "parcelas": parcelas, "aplicavel": False}

    direcao = _direcao(candidate)
    if direcao not in ("under", "over"):
        return {"total": 0.0, "parcelas": parcelas, "aplicavel": False}

    # O contexto empurra o volume PRA CIMA. Logo ele contradiz "under" e
    # confirma "over" -- so' o lado contrariado e' penalizado. Confirmar nao
    # gera bonus: o motor ja' tem sinal estatistico suficiente pro Over, e
    # premiar aqui seria contar a mesma evidencia duas vezes (o mesmo
    # double-counting que compare_matchup ja' teve que corrigir).
    if direcao != "under":
        return {"total": 0.0, "parcelas": parcelas, "aplicavel": True}

    stakes = contexto.get("stakes", 0.5)
    tie = contexto.get("tie") or {}
    if stakes >= STAKES_DECISIVO:
        peso = min((stakes - STAKES_DECISIVO) / (1.0 - STAKES_DECISIVO), 1.0) * 0.06
        total += peso
        parcelas.append({
            "sinal": "decisao",
            "peso": round(peso, 4),
            "detalhe": ", ".join(contexto.get("descricao") or ["mata-mata"]),
        })

    if tie.get("precisa_de_resultado"):
        # Um lado obrigado a atacar abre o jogo; os dois obrigados abre mais.
        peso = 0.04 if tie["precisa_de_resultado"] == "ambos" else 0.03
        total += peso
        alvo = {"home": "mandante", "away": "visitante", "ambos": "os dois times"}[
            tie["precisa_de_resultado"]]
        parcelas.append({
            "sinal": "necessidade_de_resultado",
            "peso": round(peso, 4),
            "detalhe": f"{alvo} precisa do resultado e tende a se abrir",
        })

    rivalidade = contexto.get("rivalidade") or {}
    if rivalidade.get("label") == "rivalidade_alta":
        delta = rivalry_model.intensity_delta(rivalidade)
        peso = max(delta, 0.0) * 0.25
        total += peso
        parcelas.append({
            "sinal": "rivalidade",
            "peso": round(peso, 4),
            "detalhe": (f"confronto direto promedia {rivalidade['media_h2h']} pontos de cartao "
                        f"contra base {rivalidade['baseline']} "
                        f"({rivalidade['confrontos']} encontros)"),
        })

    return {"total": round(min(total, PENALIDADE_MAX), 4), "parcelas": parcelas, "aplicavel": True}


def evaluate(candidate: dict, contexto: dict | None) -> dict:
    """Veredito do gate pra um candidato.

    Devolve sempre: `bloqueado`, `penalidade` (a subtrair da probabilidade),
    `motivos` (lista de frases prontas) e o rastro completo. Nunca devolve so'
    um booleano -- o motor precisa poder explicar a rejeicao.
    """
    pressao = pressao_contraria(candidate, contexto)
    total = pressao["total"]
    bloqueado = total >= BLOQUEIO_LIMIAR

    motivos = []
    for p in pressao["parcelas"]:
        motivos.append(f"{p['detalhe']} (+{p['peso']*100:.0f}% de pressao contraria)")

    return {
        "bloqueado": bloqueado,
        "penalidade": 0.0 if bloqueado else total,
        "pressao_total": total,
        "motivos": motivos,
        "parcelas": pressao["parcelas"],
        "aplicavel": pressao["aplicavel"],
    }


def explicar_rejeicao(candidate: dict, veredito: dict) -> str:
    """Texto de rejeicao no formato pedido: o que foi barrado e por que, com
    o peso de cada fator."""
    if not veredito.get("motivos"):
        return ""
    cabeca = (f"{candidate.get('market_name', 'Mercado')} "
              f"{candidate.get('value_label', '')} rejeitada porque:").strip()
    linhas = [f"- {m}" for m in veredito["motivos"]]
    return "\n".join([cabeca] + linhas)
