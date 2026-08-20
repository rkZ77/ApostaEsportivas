"""Gate de contexto: barra a pick que contradiz o que a partida vai ser.

O CASO QUE ORIGINOU ESTE MODULO
-------------------------------
"Under cartoes" aprovado num Fluminense x Vasco, jogo de volta valendo
classificacao. A taxa historica vinha de 15 jogos de pontos corridos e estava
CERTA pra aquele universo. O erro nao foi de calculo, foi de universo: aquela
partida nao pertencia a distribuicao que gerou a amostra.

O MECANISMO, E POR QUE ELE E' DIRECIONAL
----------------------------------------
Time que precisa do resultado se abre, quem esta na frente recua pra segurar,
e o Under de volume passa a ser a aposta perigosa. O gate antigo
(referee_model.cards_market_eligible) era cego a direcao -- bloqueava jogo
frio inteiro e liberava jogo quente inteiro, Over e Under igualmente. Era
exatamente a cegueira que deixou o Under passar.

O QUE A MEDICAO DE 2026-08-19 CORRIGIU NESTA DESCRICAO
------------------------------------------------------
Este cabecalho afirmava que as cinco familias (escanteios, chutes, gols,
cartoes, faltas) sobem juntas quando a partida abre. Medido sobre os jogos de
volta reais da base (ver a tabela completa em tie_effect.py), duas afirmacoes
estavam erradas, e uma delas invertida:

    FALTAS CAEM pro lado que precisa reverter (-2.48 por jogo, o sinal mais
    forte da tabela). Quem persegue o resultado tem a bola, e quem tem a bola
    nao comete falta.

    CARTOES nao se movem nos lados assimetricos. Sobem no agregado EMPATADO
    (+0.70 por lado) -- que e' exatamente o Fluminense x Vasco que originou
    este modulo, entao o caso fundador continua de pe', so' que agora com o
    numero e delimitado ao cenario em que ele vale.

O que este gate faz continua correto no ESCOPO em que ele age -- mercado de
jogo inteiro, direcao Under, penalidade proporcional. O que mudou e' que
mercado de UM TIME saiu daqui: ali a pergunta e' de qual lado o volume vai, e
quem responde e' tie_effect.py, com efeito medido por papel no agregado. Ver
a checagem de `scope` em pressao_contraria.

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

from services.pick_engine import competitive_pressure, match_context_model, rivalry_model

# Familias cujo volume sobe quando a partida abre, e por isso um Under nelas
# contradiz o contexto.
#
# `fouls` SAIU da lista em 2026-08-19, e saiu por medicao, nao por gosto. A
# lista tinha sido montada sobre um mecanismo suposto -- "quem segura comete
# falta tatica, quem ataca comete falta por frustracao, logo falta sobe". Os
# jogos de volta reais da base dizem o contrario, e com folga: o lado que
# precisa reverter comete 2.48 faltas A MENOS por jogo (3.9 erros-padrao, o
# sinal mais forte de toda a medicao), e o lado que administra tambem cai
# (-1.14). Faz sentido depois de visto -- quem persegue o resultado tem a bola,
# e quem tem a bola nao comete falta.
#
# Manter `fouls` aqui deixava as duas camadas do motor discordando sobre a
# MESMA partida: este gate empurrava o Under de faltas pra baixo enquanto
# tie_effect, lendo o efeito medido, empurrava pra cima. Duas camadas em
# sentidos opostos sobre o mesmo fato nao e' conservadorismo, e' ruido.
FAMILIAS_DIRECIONAIS = ("cards", "corners", "shots", "shots_on_target", "goals")

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


#: Acima desta intensidade de necessidade competitiva (competitive_pressure,
#: 0 = ninguem precisa de nada) a partida entra na conta do gate. 0.45 exige
#: mais que "ha alguma pressao": um time a 6 pontos do Z4 com 12 rodadas pela
#: frente fica abaixo disso; um a 2 pontos com 4 rodadas passa com folga.
NECESSIDADE_DECISIVA = 0.45


def build_context(round_str: str | None, home_team_id: int, away_team_id: int,
                  h2h_matches: list | None, league_id, season,
                  baseline_cartoes: float | None, before_date=None,
                  match_date=None, league_table: list | None = None) -> dict:
    """Monta o contexto completo da partida a partir do dado ja' disponivel.

    Nenhuma chamada de API nova: `round_str` vem de `fixtures.round` (ja'
    coletado) e `h2h_matches` de MatchStatsService.get_h2h_matches(), que le
    `match_statistics`.

    `match_date` (data DESTA partida) sustenta a inferencia de perna quando a
    API nao manda o rotulo -- ver match_context_model.inferir_leg. Sem ela a
    busca da ida perde a janela de dias e a inferencia nao acontece, que e' o
    comportamento anterior.
    """
    # Com rotulo, a API ja disse qual e' a perna e a busca da ida e' a de
    # sempre. Sem rotulo, a busca precisa ser ESTRITA -- e' ela que serve de
    # prova de que este e' o jogo de volta, entao nao pode aceitar qualquer
    # encontro anterior. Ver match_context_model.inferir_leg.
    if match_context_model.parse_leg(round_str) is None:
        jogo_ida = match_context_model.encontrar_jogo_de_ida(
            h2h_matches or [], league_id, season, before_date=before_date,
            # Quem visita hoje foi o mandante da ida -- o mando inverte entre
            # as duas pernas, e e' essa inversao que identifica o confronto.
            mandante_da_ida=away_team_id, referencia=match_date)
    else:
        jogo_ida = match_context_model.encontrar_jogo_de_ida(
            h2h_matches or [], league_id, season, before_date=before_date)
    tie = match_context_model.tie_context(round_str, home_team_id, away_team_id, jogo_ida,
                                          league_id=league_id)
    rivalidade = rivalry_model.rivalry_signal(h2h_matches or [], baseline_cartoes)
    # Necessidade competitiva de pontos corridos. E' o irmao de liga do `tie`:
    # o mata-mata diz quem precisa do resultado por causa do agregado, a tabela
    # diz quem precisa por causa da temporada. Os dois abrem a partida pelo
    # mesmo mecanismo, e por isso entram no mesmo gate.
    pressao_liga = (competitive_pressure.pressao_da_partida(
        league_table, home_team_id, away_team_id, league_id) if league_table else None)

    return {
        "tie": tie,
        "rivalidade": rivalidade,
        "stakes": match_context_model.stakes_score(tie),
        "pressao_competitiva": pressao_liga,
        "descricao": (match_context_model.descrever(tie)
                      + competitive_pressure.descrever(pressao_liga)),
    }


def build_for_fixture(match_stats, fixture: dict, convergencia_cartoes: dict | None = None,
                      before_date=None, league_table: list | None = None) -> dict | None:
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
            match_date=fixture.get("match_datetime") or before_date,
            league_table=league_table,
        )
    except Exception as e:
        print(f"[CONTEXT_GATE] Contexto indisponivel para fixture "
              f"{fixture.get('fixture_id')}: {e}")
        return None


def pressao_contraria(candidate: dict, contexto: dict | None,
                      delegar_lados: bool = False) -> dict:
    """Quanto o contexto contradiz a direcao deste candidato.

    `delegar_lados=True` entrega os mercados de UM TIME (scope home/away)
    pra tie_effect e nao age neles -- ver a checagem de escopo no corpo.
    Default False de proposito: com o efeito medido desligado
    (config.use_tie_effect), este gate volta a ser o unico a olhar o
    agregado, e nenhum candidato fica sem camada nenhuma.

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

    # MERCADO DE UM TIME SO' E' DE OUTRA CAMADA (2026-08-19). Este gate mede
    # "quanto a partida contradiz esta direcao" sem olhar de QUEM e' o mercado
    # -- ele nasceu pra escanteio/cartao do jogo inteiro, onde essa pergunta
    # basta. Num "Escanteios Casa" a pergunta certa e' outra: aquele lado
    # especifico ataca ou administra? Quem responde isso e' tie_effect, com o
    # efeito medido POR PAPEL no agregado.
    #
    # Os dois lendo o mesmo agregado cobrariam duas vezes pelo mesmo fato --
    # o double-counting que o pedido nomeia. A divisao e' de escopo: total
    # aqui, lado la'.
    if delegar_lados and candidate.get("scope") in ("home", "away"):
        return {"total": 0.0, "parcelas": parcelas, "aplicavel": False,
                "delegado_a": "tie_effect"}

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

    # Necessidade de tabela: mesmo mecanismo do agregado, outra competicao.
    # Time que precisa vencer pra nao cair se lanca igual a quem precisa
    # reverter um 1x0 -- e o Under sofre igual nos dois casos.
    #
    # A ASSIMETRIA PESA MAIS QUE A INTENSIDADE, e nao e' detalhe: dois times
    # desesperados costumam TRAVAR o jogo (nenhum quer perder), enquanto um
    # desesperado contra um acomodado abre. Por isso a parcela cresce com a
    # diferenca entre as duas necessidades, nao so' com a soma delas.
    pressao_liga = contexto.get("pressao_competitiva") or {}
    if pressao_liga.get("disponivel") and pressao_liga["intensidade"] >= NECESSIDADE_DECISIVA:
        acima = (pressao_liga["intensidade"] - NECESSIDADE_DECISIVA) / (1.0 - NECESSIDADE_DECISIVA)
        peso = min(acima, 1.0) * 0.035 + min(pressao_liga["assimetria"], 1.0) * 0.025
        total += peso
        detalhe = "; ".join(competitive_pressure.descrever(pressao_liga)) or "tabela apertada"
        parcelas.append({
            "sinal": "necessidade_de_tabela",
            "peso": round(peso, 4),
            "detalhe": detalhe,
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


def evaluate(candidate: dict, contexto: dict | None,
             delegar_lados: bool = False) -> dict:
    """Veredito do gate pra um candidato.

    Devolve sempre: `bloqueado`, `penalidade` (a subtrair da probabilidade),
    `motivos` (lista de frases prontas) e o rastro completo. Nunca devolve so'
    um booleano -- o motor precisa poder explicar a rejeicao.
    """
    pressao = pressao_contraria(candidate, contexto, delegar_lados=delegar_lados)
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
