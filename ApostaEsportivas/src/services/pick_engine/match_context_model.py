"""Contexto de eliminatoria: fase, ida ou volta, placar da ida, agregado e
quem precisa de resultado.

O CASO QUE ORIGINOU ESTE MODULO
-------------------------------
"Under cartoes" aprovado num Fluminense x Vasco, jogo de VOLTA valendo
classificacao. A taxa historica vinha de 15 jogos de campeonato de pontos
corridos, e nada no motor sabia que aquela partida tinha regulamento, agregado
e eliminacao em jogo. O motor calculava certo a pergunta errada.

O QUE E' DERIVAVEL SEM COLETOR NOVO
-----------------------------------
Tudo aqui sai de dado que ja' esta no banco:

  fase e perna       -> `fixtures.round`, texto da API-Football ja' coletado
                        ("Quarter-finals - 2nd Leg", "Round of 16 - 1st Leg")
  placar da ida      -> MatchStatsService.get_h2h_matches() filtrado pela
                        MESMA competicao e temporada; o encontro anterior
                        recente entre os dois e' a ida
  agregado           -> soma dos gols dos dois jogos, com o mando invertido
  quem precisa       -> consequencia do agregado

A auditoria tinha registrado "H2H nao tem coletor". O diagnostico estava
errado: faltava a consulta, nao a coleta -- `match_statistics` sempre teve os
dois times de cada partida.

POR QUE ISSO IMPORTA PRA CARTOES E NAO SO' PRA GOLS
---------------------------------------------------
Jogo de volta com eliminacao em jogo muda o comportamento das duas equipes ao
mesmo tempo: quem esta atras arrisca mais, quem esta na frente segura o
resultado, e as duas coisas produzem falta tatica. E' o pior contexto possivel
pra um "Under cartoes", e um dos melhores pra um "Over" -- por isso o sinal
daqui e' DIRECIONAL, nao apenas um bonus de intensidade.
"""
from __future__ import annotations

from datetime import datetime

import re

from services.pick_engine import competition_profile

# "2nd Leg", "1st leg", "Leg 2", "2ª Mão" -- a API-Football manda em ingles,
# mas o padrao aceita variantes pra nao quebrar se o rotulo mudar de forma.
_LEG_PATTERNS = (
    (re.compile(r"\b1st\s+leg\b", re.I), 1),
    (re.compile(r"\b2nd\s+leg\b", re.I), 2),
    (re.compile(r"\bleg\s*1\b", re.I), 1),
    (re.compile(r"\bleg\s*2\b", re.I), 2),
)

# Rotulos de fase, do mais decisivo pro menos. A ordem importa: "Semi-finals"
# contem "final" como substring, entao semi tem que ser testado antes.
_FASES = (
    (re.compile(r"\bthird\s+place\b", re.I), "TERCEIRO_LUGAR"),
    (re.compile(r"\bsemi", re.I),            "SEMIFINAL"),
    (re.compile(r"\bquarter", re.I),         "QUARTAS"),
    (re.compile(r"\bround\s+of\s+16\b", re.I), "OITAVAS"),
    (re.compile(r"\bround\s+of\s+32\b", re.I), "TRINTA_E_DOIS"),
    # Repescagem/preliminar tem que ser testada ANTES de "playoff" e de
    # "final": a API-Football rotula a repescagem da Champions como "Knockout
    # Round Play-offs" e a da Libertadores como "Play-in"/"Preliminary Round",
    # e sem esta linha as tres cairiam em PLAYOFF, que pesa mais.
    (re.compile(r"\brepechage\b|\bplay[\s-]?in\b|\bpreliminary\b|"
                r"\bknockout\s+round\s+play[\s-]?offs?\b|\brepescagem\b", re.I), "REPESCAGEM"),
    (re.compile(r"\bfinal\b", re.I),         "FINAL"),
    (re.compile(r"\bplay[\s-]?off", re.I),   "PLAYOFF"),
    (re.compile(r"\bgroup\b", re.I),         "GRUPOS"),
)

# Peso de "quanto esta em jogo", por fase. Usado pra modular a intensidade --
# uma final decide tudo, uma terceira fase de copa decide bem menos. Nao e'
# probabilidade, e' importancia relativa (0-1).
_PESO_FASE = {
    "FINAL": 1.00, "SEMIFINAL": 0.85, "QUARTAS": 0.70,
    "OITAVAS": 0.60, "TRINTA_E_DOIS": 0.50, "PLAYOFF": 0.55,
    "REPESCAGEM": 0.45, "TERCEIRO_LUGAR": 0.35, "GRUPOS": 0.30,
}


_FASES_MATA_MATA = ("FINAL", "SEMIFINAL", "QUARTAS", "OITAVAS",
                    "TRINTA_E_DOIS", "PLAYOFF", "REPESCAGEM", "TERCEIRO_LUGAR")

# Formatos que o motor distingue. PONTOS_CORRIDOS e' o caso normal; os dois de
# copa sao separados porque a pergunta que se faz deles e' outra (ver
# resolver_formato). DESCONHECIDO existe pra nunca ter que escolher entre
# advinhar e fingir que a partida e' comum.
PONTOS_CORRIDOS = "PONTOS_CORRIDOS"
COPA_JOGO_UNICO = "COPA_JOGO_UNICO"
COPA_IDA_E_VOLTA = "COPA_IDA_E_VOLTA"
FORMATO_DESCONHECIDO = "DESCONHECIDO"

# Distancia maxima entre ida e volta pra tratar dois encontros como o MESMO
# confronto. Legs ficam de 6 a 9 dias; encontro de fase de grupos, meses. A
# janela e' o que separa os dois casos -- ver inferir_leg.
_JANELA_IDA_VOLTA_DIAS = 21


def _para_data(valor):
    """date de um match_date/match_datetime, aceitando str, date ou datetime."""
    if valor is None:
        return None
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            return None
    return valor.date() if isinstance(valor, datetime) else valor


def parse_leg(round_str: str | None) -> int | None:
    """1 (ida), 2 (volta) ou None quando o texto nao diz."""
    if not round_str:
        return None
    for padrao, numero in _LEG_PATTERNS:
        if padrao.search(round_str):
            return numero
    return None


def inferir_leg(round_str: str | None, jogo_de_ida: dict | None) -> tuple:
    """(leg, origem) -- le o rotulo e, quando ele nao diz, INFERE pelo confronto.

    A API-Football nem sempre manda a perna. Medido em producao em 2026-08-10:
    os 8 jogos de oitavas da Libertadores no banco vinham todos como
    "Round of 16", sem "1st leg"/"2nd leg". Com isso `parse_leg` devolvia None,
    `is_jogo_de_volta` ficava False sempre e -- o pior -- `encontrar_jogo_de_ida`
    nunca era consultado, porque estava atras de um `if leg != 2`. Nas VOLTAS o
    motor trataria cada jogo como se fosse ida: sem agregado, sem saber quem
    precisa do resultado, e sem os pontos de stakes que a decisao merece.

    A inferencia usa a inversao de mando, que e' o que define ida e volta: num
    confronto de dois jogos, quem visita hoje foi obrigatoriamente o MANDANTE da
    ida. Quem aplica esse filtro (mais o da janela de dias e o da mesma
    competicao) e' encontrar_jogo_de_ida; aqui so' se conclui.

    Rotulo explicito sempre vence a inferencia -- quando a API diz, ela sabe.
    """
    leg = parse_leg(round_str)
    if leg is not None:
        return leg, "rotulo"
    if jogo_de_ida is not None and parse_fase(round_str) in _FASES_MATA_MATA:
        return 2, "inferido"
    return None, None


def parse_fase(round_str: str | None) -> str | None:
    """Rotulo de fase a partir do texto do round. None quando nao reconhece --
    nunca advinha (mesma postura de competition_profile.classify_round_phase)."""
    if not round_str:
        return None
    for padrao, nome in _FASES:
        if padrao.search(round_str):
            return nome
    return None


def resolver_formato(league_id, fase: str | None, leg_do_rotulo: int | None,
                     jogo_de_ida: dict | None) -> tuple:
    """(formato, origem) -- o formato REAL desta fase, por evidencia primeiro.

    "Nao assuma que toda competicao chamada copa possui ida e volta" e' o
    pedido, e a ordem abaixo e' a resposta. Cada fonte so' e' consultada
    quando a anterior nao respondeu, e a mais forte e' a que menos depende de
    cadastro:

      1. `rotulo`     a API escreveu "1st Leg"/"2nd Leg". Ela sabe. So' vale
                      o rotulo LITERAL (parse_leg) -- a perna INFERIDA nao
                      entra aqui, senao a origem diria "rotulo" pra uma
                      conclusao que veio do confronto, e a distincao entre "a
                      API disse" e "o motor deduziu" e' justamente o que
                      `formato_origem` existe pra carregar.
      2. `confronto`  existe um jogo anterior entre os dois, na mesma
                      competicao e temporada, com o mando invertido e dentro
                      da janela de dias. Isso nao e' indicio: e' a definicao
                      de confronto de duas pernas.
      3. `regulamento` o que competition_profile declara pra aquela fase --
                      so' consultado quando nao ha evidencia, e e' o que cobre
                      o JOGO DE IDA (onde nao existe confronto anterior pra
                      olhar) e a final unica de um torneio de duas pernas.
      4. nada          fase de mata-mata sem evidencia e sem regulamento
                      cadastrado -> DESCONHECIDO. Nao vira "jogo unico" por
                      omissao: jogo unico e' uma afirmacao, e o motor nao a
                      tem.

    Fora de mata-mata (fase de grupos, rodada de campeonato, fase que o parser
    nao reconheceu) o formato e' PONTOS_CORRIDOS -- nao ha confronto agregado
    a reconstruir, e e' o caminho que a esmagadora maioria dos jogos toma.
    """
    if fase not in _FASES_MATA_MATA:
        return PONTOS_CORRIDOS, "fase"
    if leg_do_rotulo is not None:
        return COPA_IDA_E_VOLTA, "rotulo"
    if jogo_de_ida is not None:
        return COPA_IDA_E_VOLTA, "confronto"
    declarado = competition_profile.formato_declarado(league_id, fase)
    if declarado:
        return declarado, "regulamento"
    return FORMATO_DESCONHECIDO, None


def peso_da_fase(fase: str | None) -> float:
    """Importancia relativa da fase (0-1). Fase desconhecida vale 0.30, o
    mesmo de fase de grupos -- na duvida, assume o cenario de menor pressao,
    porque superestimar importancia inflaria a intensidade de todo jogo cujo
    rotulo o parser nao entendeu."""
    return _PESO_FASE.get(fase or "", 0.30)


def _gols_do_time(jogo: dict, team_id: int) -> int | None:
    if jogo.get("home_team_id") == team_id:
        return jogo.get("home_goals")
    if jogo.get("away_team_id") == team_id:
        return jogo.get("away_goals")
    return None


def encontrar_jogo_de_ida(h2h: list, league_id, season, before_date=None,
                          mandante_da_ida=None, referencia=None,
                          janela_dias: int = _JANELA_IDA_VOLTA_DIAS) -> dict | None:
    """A ida do confronto atual: encontro mais recente entre os dois times na
    MESMA competicao e temporada.

    Restringir a competicao e a temporada e' o que separa "a ida deste mata-
    mata" de "o classico do campeonato tres meses atras". Sem esse filtro o
    agregado sairia somando jogos que nao fazem parte do confronto.

    Dois filtros opcionais, que existem pra sustentar a INFERENCIA de perna
    quando a API nao manda o rotulo (ver inferir_leg) -- sem eles a funcao se
    comporta como antes:

    `mandante_da_ida`: time que precisa ter sido o MANDANTE naquele jogo. Num
    confronto de dois jogos o mando inverte, entao quem visita hoje jogou em
    casa na ida. E' o filtro que impede confundir a ida com o jogo do primeiro
    turno de um grupo, que pode ter sido em qualquer mando.

    `referencia`/`janela_dias`: data desta partida e distancia maxima ate' o
    encontro anterior. Legs ficam de 6 a 9 dias; encontro de fase de grupos,
    meses. E' o que impede tratar um jogo de grupo de marco como a ida de uma
    quartas de agosto (cenario real: em Libertadores dois times do mesmo grupo
    podem se reencontrar no mata-mata a partir das quartas).
    """
    if not h2h:
        return None
    ref = _para_data(referencia)
    if mandante_da_ida is not None and ref is None:
        # Pediram a busca ESTRITA (a que sustenta a inferencia de perna) sem a
        # data desta partida. Sem a janela nao da' pra separar a ida de um
        # encontro de fase de grupos, e afirmar "e' a volta" com base so' no
        # mando seria advinhar. Mesma postura de parse_fase: na duvida, None.
        return None
    candidatos = []
    for j in h2h:
        if j.get("league_id") != league_id:
            continue
        if not (season is None or j.get("season") is None or j.get("season") == season):
            continue
        if before_date is not None and not (j.get("match_date") and j["match_date"] < before_date):
            continue
        if mandante_da_ida is not None and j.get("home_team_id") != mandante_da_ida:
            continue
        if ref is not None:
            quando = _para_data(j.get("match_date"))
            if quando is None or not (0 <= (ref - quando).days <= janela_dias):
                continue
        candidatos.append(j)
    if not candidatos:
        return None
    return max(candidatos, key=lambda j: j.get("match_date") or 0)


# Deslocamento de volume OFENSIVO DO LADO que precisa reverter o agregado,
# 0-1, por tamanho da desvantagem. Nao e' escala inventada: e' a forma da
# medicao de 2026-08-19 sobre os jogos de volta reais da base de producao
# (11 confrontos com estatistica completa, baseline casado por mando):
#
#     lado atras no agregado   escanteios +1.98 (ep 1.18)  chutes +2.95 (ep 1.61)
#     lado na frente           escanteios -1.66 (ep 1.52)  chutes -0.30 (ep 2.61)
#     agregado empatado        escanteios -0.64 (ep 0.99)  chutes +0.49 (ep 1.66)
#
# Duas conclusoes, e as duas contrariam o que "mata-mata abre o jogo" sugere:
#
#   1. AGREGADO EMPATADO NAO DESLOCA VOLUME. E' o cenario de maior tensao
#      (e stakes_score continua dizendo isso, porque importancia e' outra
#      coisa), mas os dois times se anulam e a partida sai igual a uma
#      partida comum. Por isso o empate vale 0.0 aqui, nao o maximo.
#   2. O EFEITO E' REDISTRIBUICAO, NAO CRIACAO. O total da partida quase nao
#      se move (+0.95 escanteios, ep 1.04 -- indistinguivel de zero); o que
#      muda e' de QUEM sao os escanteios. Ver tie_effect.py, que e' quem usa
#      esta escala e que por isso quase nao age em mercado de jogo inteiro.
_PRESSAO_POR_DIFERENCA = {0: 0.00, 1: 0.60, 2: 0.85, 3: 1.00}

# Quem esta na frente segura, mas segura MENOS do que o outro ataca -- os dois
# numeros medidos acima nao sao simetricos (-1.66 contra +1.98).
_FATOR_DE_QUEM_ADMINISTRA = 0.80


def _pressao_por_lado(diferenca: int | None, peso_fase: float) -> dict:
    """Necessidade ofensiva de cada lado, -1 a +1, do ponto de vista do
    MANDANTE DE HOJE. Positivo = precisa atacar; negativo = pode administrar.

    `diferenca` e' o agregado pelo mandante atual (+1 = mandante ganhando o
    confronto por 1). O peso da fase modula: precisar de um gol numa final
    aperta mais que numa repescagem.
    """
    if diferenca is None:
        return {"home": 0.0, "away": 0.0, "magnitude": 0.0,
                "papel_home": None, "papel_away": None, "aplicavel": False}
    intensidade = _PRESSAO_POR_DIFERENCA.get(min(abs(diferenca), 3), 1.00)
    # peso_fase vai de 0.30 (grupos) a 1.00 (final); reescalado pra nao zerar
    # a fase mais fraca nem inflar a mais forte.
    modulador = 0.70 + 0.30 * peso_fase
    forca = round(intensidade * modulador, 4)
    if diferenca == 0:
        return {"home": 0.0, "away": 0.0, "magnitude": 0.0,
                "papel_home": "empatado", "papel_away": "empatado", "aplicavel": True}
    if diferenca > 0:                      # mandante na frente: ele administra
        lados = {"home": round(-forca * _FATOR_DE_QUEM_ADMINISTRA, 4), "away": forca,
                 "papel_home": "na_frente", "papel_away": "atras"}
    else:                                  # mandante atras: ele ataca
        lados = {"home": forca, "away": round(-forca * _FATOR_DE_QUEM_ADMINISTRA, 4),
                 "papel_home": "atras", "papel_away": "na_frente"}
    # `magnitude` e' a forca do confronto SEM a assimetria de papel embutida.
    # Existe porque tie_effect ja' tem o efeito de cada papel MEDIDO em separado
    # (atras e na_frente nao sao espelhos um do outro nos dados), e usar os
    # numeros com sinal acima aplicaria a assimetria duas vezes.
    return {**lados, "magnitude": forca, "aplicavel": True}


def tie_context(round_str: str | None, home_team_id: int, away_team_id: int,
                jogo_de_ida: dict | None = None, league_id=None) -> dict:
    """Retrato completo do confronto eliminatorio.

    `home_team_id`/`away_team_id` sao os do jogo A SER ANALISADO (a volta,
    quando houver). O mando se inverte entre ida e volta, e e' justamente onde
    um calculo de agregado costuma errar de sinal -- por isso os gols de cada
    lado sao resolvidos por team_id, nunca pela coluna home/away.

    `league_id` (2026-08-19) traz o REGULAMENTO da competicao: formato
    declarado da fase, prorrogacao, penaltis e gol fora. Opcional -- sem ele o
    formato ainda sai da evidencia do confronto, so' nao ha regra de
    classificacao pra expor.

    Sempre devolve os numeros brutos junto dos rotulos.
    """
    fase = parse_fase(round_str)
    leg, leg_origem = inferir_leg(round_str, jogo_de_ida)
    is_mata_mata = fase in _FASES_MATA_MATA
    formato, formato_origem = resolver_formato(
        league_id, fase, parse_leg(round_str), jogo_de_ida)
    regras = competition_profile.regras_de_mata_mata(league_id)

    contexto = {
        "fase": fase,
        "leg": leg,
        # "rotulo" (a API disse) ou "inferido" (deduzido do confronto anterior
        # com o mando invertido). Sempre exposto: quem explica o pick precisa
        # poder dizer de onde veio a afirmacao de que este e' o jogo de volta.
        "leg_origem": leg_origem,
        "is_mata_mata": bool(is_mata_mata),
        "is_jogo_de_volta": leg == 2,
        "peso_fase": peso_da_fase(fase),
        "formato": formato,
        # "rotulo" | "confronto" | "regulamento" | "fase" | None -- de onde
        # veio a afirmacao de formato. Sem isso nao da' pra distinguir
        # "sabemos que e' jogo unico" de "ninguem disse o contrario".
        "formato_origem": formato_origem,
        "regras": {
            # Tri-estado preservado ate' a ponta: None = nao declarado.
            # Nenhum calculo deste motor aplica gol fora sem True literal.
            "gol_fora": regras.away_goals,
            "prorrogacao": regras.prorrogacao,
            "penaltis": regras.penaltis,
        },
        "placar_ida": None,
        "agregado_home": None,
        "agregado_away": None,
        "diferenca_agregada": None,
        "gols_para_reverter": None,
        "lider_agregado": None,
        "precisa_de_resultado": None,
        "empate_classifica": None,
        "pressao_por_lado": {"home": 0.0, "away": 0.0, "aplicavel": False},
        "is_approximation": True,
    }

    if leg != 2 or not jogo_de_ida:
        return contexto

    gols_home = _gols_do_time(jogo_de_ida, home_team_id)
    gols_away = _gols_do_time(jogo_de_ida, away_team_id)
    if gols_home is None or gols_away is None:
        return contexto

    contexto["placar_ida"] = {
        "data": jogo_de_ida.get("match_date"),
        "gols_mandante_atual": gols_home,
        "gols_visitante_atual": gols_away,
    }
    # Agregado ANTES desta partida: o que cada um fez na ida.
    contexto["agregado_home"] = gols_home
    contexto["agregado_away"] = gols_away
    contexto["diferenca_agregada"] = gols_home - gols_away
    # Quantos gols o lado atras precisa so' pra empatar o agregado. E' o
    # numero que separa "reverter um 1x0" de "reverter um 3x0", e o que o
    # motor ao vivo recalcula a cada gol.
    contexto["gols_para_reverter"] = abs(gols_home - gols_away) or None

    if gols_home > gols_away:
        contexto["lider_agregado"] = "home"
        contexto["precisa_de_resultado"] = "away"
        contexto["empate_classifica"] = "home"
    elif gols_away > gols_home:
        contexto["lider_agregado"] = "away"
        contexto["precisa_de_resultado"] = "home"
        contexto["empate_classifica"] = "away"
    else:
        # Ida empatada: ninguem tem vantagem, os dois precisam vencer e o
        # empate leva a prorrogacao/penaltis. E' o cenario de maior tensao --
        # os dois times jogam pra ganhar ate' o fim.
        contexto["lider_agregado"] = None
        contexto["precisa_de_resultado"] = "ambos"
        contexto["empate_classifica"] = None

    contexto["pressao_por_lado"] = _pressao_por_lado(
        contexto["diferenca_agregada"], contexto["peso_fase"])
    return contexto


def stakes_score(contexto: dict | None) -> float:
    """Quanto esta em jogo nesta partida, 0-1 (0.5 = jogo comum).

    Combina fase, ser jogo de volta e a situacao do agregado. Jogo de ida de
    oitavas pesa menos que volta de semifinal com agregado empatado -- e' a
    diferenca que o motor nao enxergava.
    """
    if not contexto or not contexto.get("is_mata_mata"):
        return 0.5

    score = 0.5 + (contexto["peso_fase"] - 0.30) * 0.35

    if contexto.get("is_jogo_de_volta"):
        # A volta decide; a ida ainda tem 90 minutos depois pra corrigir.
        score += 0.10
        if contexto.get("precisa_de_resultado") == "ambos":
            # Agregado empatado: os dois precisam vencer, tensao maxima.
            score += 0.12
        elif contexto.get("precisa_de_resultado"):
            # Um lado obrigado a atacar e outro segurando: assimetria que
            # produz falta tatica dos dois lados.
            score += 0.08

    return round(max(min(score, 1.0), 0.0), 4)


def descrever(contexto: dict | None) -> list:
    """Frases prontas pra explicacao de pick/rejeicao. Texto derivado dos
    numeros, nunca inventado -- se o campo nao existe, a frase nao aparece."""
    if not contexto or not contexto.get("is_mata_mata"):
        return []

    partes = []
    nomes = {"FINAL": "final", "SEMIFINAL": "semifinal", "QUARTAS": "quartas de final",
             "OITAVAS": "oitavas de final", "TRINTA_E_DOIS": "fase de 32",
             "PLAYOFF": "play-off", "REPESCAGEM": "repescagem",
             "TERCEIRO_LUGAR": "disputa de terceiro lugar"}
    fase_txt = nomes.get(contexto.get("fase"), "mata-mata")
    formato = contexto.get("formato")

    if contexto.get("leg") == 2:
        partes.append(f"jogo de volta de {fase_txt}")
    elif contexto.get("leg") == 1:
        partes.append(f"jogo de ida de {fase_txt}")
    elif formato == COPA_JOGO_UNICO:
        partes.append(f"{fase_txt} em jogo unico")
    else:
        partes.append(f"partida de {fase_txt}")

    placar = contexto.get("placar_ida")
    if placar:
        partes.append(
            f"ida terminou {placar['gols_mandante_atual']} a {placar['gols_visitante_atual']} "
            f"para o mandante de hoje"
        )
    faltam = contexto.get("gols_para_reverter")
    if contexto.get("precisa_de_resultado") == "ambos":
        partes.append("agregado empatado, os dois precisam do resultado")
    elif contexto.get("precisa_de_resultado") == "home":
        partes.append(f"mandante precisa de {faltam} gol(s) so' pra empatar o agregado "
                      f"e tende a assumir a iniciativa")
        partes.append("visitante joga com a vantagem e pode administrar")
    elif contexto.get("precisa_de_resultado") == "away":
        partes.append(f"visitante precisa de {faltam} gol(s) so' pra empatar o agregado "
                      f"e tende a assumir a iniciativa")
        partes.append("mandante joga com a vantagem e pode administrar")

    # Regra de classificacao -- so' aparece quando a competicao a DECLARA.
    # Silencio aqui e' proposital: dizer "sem gol fora" numa competicao cujo
    # regulamento nao esta cadastrado seria afirmar o que nao se sabe.
    regras = contexto.get("regras") or {}
    if formato == COPA_IDA_E_VOLTA and regras.get("gol_fora") is True:
        partes.append("competicao usa criterio de gol fora")
    if contexto.get("precisa_de_resultado") == "ambos":
        if regras.get("prorrogacao") is True:
            partes.append("empate no agregado leva a prorrogacao")
        elif regras.get("prorrogacao") is False and regras.get("penaltis") is True:
            partes.append("empate no agregado vai direto aos penaltis")

    return partes
