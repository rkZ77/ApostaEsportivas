"""Fonte unica de liquidacao (settlement) de picks.

TODA decisao GREEN/RED/PUSH/HALF-WIN/HALF-LOSS do sistema passa por aqui:
o job em lote (services/ai_result_checker_*.py, que le de match_statistics)
e o caminho ao vivo do site (website/backend/routers/live.py, que le direto
da API-Football). Antes existiam duas implementacoes paralelas dessa mesma
matematica e elas divergiam -- por exemplo, mercado de time nomeado no texto
("Escanteios France Mais/Menos") era resolvido pelo total num lado e pelo
time do outro.

Modulo sem dependencia nenhuma (nem banco, nem rede, nem env) de proposito:
e' o que permite o backend do site importa-lo pelo mesmo caminho de
PIPELINE_SRC_PATH ja usado por routers/admin.py, e permite testar cada regra
sem subir nada.

## As tres invariantes

1. ESTATISTICA AUSENTE NUNCA VIRA ZERO. Se o provedor ainda nao publicou a
   contagem, o mercado NAO e' liquidado (`(None, 0)`) e o pick fica pendente
   ate a proxima passada. Foi exatamente a violacao dessa regra que gerou o
   caso real que originou esta auditoria: fixture 1546854 (Fortaleza EC x
   Palmeiras, 05/08/2026), pick "Escanteios Mais/Menos · Over 9.5". No
   instante do apito final /fixtures/statistics ainda nao tinha devolvido a
   estatistica; `home_stats.get("Corner Kicks", 0)` produziu 0 escanteios,
   0 > 9.5 e' falso, e o pick foi gravado RED. O jogo terminou 6 + 4 = 10
   escanteios, ou seja GREEN. O erro nao estava na comparacao -- estava em
   ter tratado "nao sei" como "zero".

2. LINHA FORA DA GRADE ASIATICA NUNCA VIRA RED. Qualquer linha que nao seja
   multipla de 0.25 (ou que nao tenha sido lida) devolve `(None, 0)` --
   "nao sei resolver" -- em vez de cair num `return RED` de fim de funcao.

3. LINHA DE QUARTO-DE-BOLA E' SEMPRE DIVIDIDA EM DUAS METADES. Nao existe
   tabela de casos .25/.75 aqui: a linha e' partida nas duas meia-linhas
   vizinhas, cada metade e' resolvida pela mesma funcao das linhas
   inteiras/meias, e a media das duas da' HALF-WIN/HALF-LOSS naturalmente.
   Uma regra so', valida pra todos os mercados de total e de handicap.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# ── Vocabulario de resultado (o mesmo do frontend, ver
# website/frontend/src/utils/resultStyle.ts::PickResult) ────────────────────
GREEN = "GREEN"
RED = "RED"
PUSH = "PUSH"
HALF_WIN = "HALF-WIN"
HALF_LOSS = "HALF-LOSS"

RESULT_LABELS = frozenset({GREEN, RED, PUSH, HALF_WIN, HALF_LOSS})

_ONE = Decimal("1")
_ZERO = Decimal("0")
_HALF = Decimal("0.5")
_QUARTER = Decimal("0.25")

# factor = quanto da stake foi ganho (+1) ou perdido (-1) por unidade apostada
_FACTOR_TO_RESULT = {
    Decimal("1"): GREEN,
    Decimal("0.5"): HALF_WIN,
    Decimal("0"): PUSH,
    Decimal("-0.5"): HALF_LOSS,
    Decimal("-1"): RED,
}

#: Retorno padrao pra "nao da' pra liquidar" -- nunca confundir com RED.
UNRESOLVED: tuple[None, Decimal] = (None, _ZERO)


###############################################################################
# Conversao numerica
###############################################################################
def to_decimal(value) -> Decimal | None:
    """Converte pra Decimal exato, ou None se nao for numero.

    Passa por `str()` de proposito: `Decimal(9.5)` a partir de float traria o
    lixo binario (9.5 e' exato, mas 9.1 nao seria) e quebraria as comparacoes
    de igualdade que decidem PUSH. Aceita virgula decimal (pt-BR) porque a
    linha as vezes chega como texto vindo da casa de apostas ("9,5").
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # bool e' subclasse de int; nunca e' uma linha
        return None
    try:
        return Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError, ArithmeticError):
        return None


###############################################################################
# Leitura da linha
###############################################################################
_OVER_WORDS = ("over", "acima de", "acima", "mais de", "mais", "+de")
_UNDER_WORDS = ("under", "abaixo de", "abaixo", "menos de", "menos", "-de")
_YES_WORDS = ("yes", "sim")
_NO_WORDS = ("no", "nao", "não")

_HOME_WORDS = ("home", "casa", "mandante")
_AWAY_WORDS = ("away", "visitante", "visita", "fora")

_NUMBER_RE = re.compile(r"[+-]?\d+(?:\.\d+)?")

# Limiar inclusivo: "3 ou mais defesas" e' P(X >= 3), nao Over 3.0. As duas
# leituras so' divergem em UM ponto -- o proprio 3 -- e e' justamente o ponto
# que decide o pick. Ver o comentario em parse_line.
_OU_MAIS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:ou\s+mais|or\s+more)")
_OU_MENOS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:ou\s+menos|or\s+less|or\s+fewer)")
_MEIA_LINHA = Decimal("0.5")


def parse_line(line, home_team: str | None = None, away_team: str | None = None) -> dict:
    """Le o texto da linha e devolve {op, value, side, raw}.

    op    -- "over" | "under" | "yes" | "no" | None
    value -- Decimal da linha, ou None
    side  -- "home" | "away" | None (lado embutido no texto: "Home +0.25")

    Nao adivinha: texto que nao encaixa em nada devolve op=None, e quem chama
    decide (tipicamente: nao liquidar).
    """
    raw = "" if line is None else str(line)
    ln = raw.strip().lower()

    out = {"op": None, "value": None, "side": None, "raw": raw}
    if not ln:
        return out

    # Sim/Nao (BTTS) -- comparacao exata, pra "no" nao casar dentro de outra palavra
    if ln in _YES_WORDS:
        out["op"] = "yes"
        return out
    if ln in _NO_WORDS:
        out["op"] = "no"
        return out

    ln_num = ln.replace(",", ".")
    numbers = _NUMBER_RE.findall(ln_num)
    if numbers:
        out["value"] = to_decimal(numbers[0])

    # LIMIAR INCLUSIVO ("N ou mais"), corrigido em 2026-08-10.
    #
    # Este e' o formato do pick de defesas de goleiro -- engine_pipelines/
    # goleiros_pipeline.py grava "Everson · 3 ou mais defesas" e calcula a
    # probabilidade como P(X >= 3) = prob_over(2.5). A leitura generica abaixo
    # via "mais" e devolvia Over 3.0, uma LINHA CHEIA: goleiro com exatamente 3
    # defesas era gravado PUSH ("stake devolvida") num pick que pagou. Motor e
    # liquidacao discordando sobre o mesmo numero, no unico ponto em que as
    # duas leituras diferem.
    #
    # A traducao pra meia-linha (>= 3 vira Over 2.5) e' o que mantem UMA
    # gramatica: settle_over_under nao precisa aprender um terceiro operador, e
    # o ticker ao vivo (que le a linha por aqui, via _extract_line) passa a
    # concordar com o job em lote de graca.
    limiar_mais = _OU_MAIS_RE.search(ln_num)
    limiar_menos = _OU_MENOS_RE.search(ln_num)
    if limiar_mais:
        out["op"] = "over"
        out["value"] = to_decimal(limiar_mais.group(1)) - _MEIA_LINHA
    elif limiar_menos:
        out["op"] = "under"
        out["value"] = to_decimal(limiar_menos.group(1)) + _MEIA_LINHA
    elif any(w in ln for w in _OVER_WORDS):
        out["op"] = "over"
    elif any(w in ln for w in _UNDER_WORDS):
        out["op"] = "under"

    if any(w in ln for w in _HOME_WORDS):
        out["side"] = "home"
    elif any(w in ln for w in _AWAY_WORDS):
        out["side"] = "away"
    elif home_team and home_team.strip() and home_team.strip().lower() in ln:
        out["side"] = "home"
    elif away_team and away_team.strip() and away_team.strip().lower() in ln:
        out["side"] = "away"

    return out


###############################################################################
# Grade asiatica
###############################################################################
def line_grid(line) -> str | None:
    """"whole" (x.0) | "half" (x.5) | "quarter" (x.25 / x.75) | None.

    None = linha fora da grade asiatica (nao e' multipla de 0.25) e portanto
    nao liquidavel. Vale pra linha negativa tambem: a classificacao usa o
    numero de quartos como inteiro Python (modulo com sinal de piso), nao
    `line % 1` do Decimal -- `Decimal("-9.5") % 1` da' -0.5, e comparar isso
    com 0.5 dava falso, o que jogava toda linha negativa no `return RED` que
    fechava a funcao antiga.
    """
    value = to_decimal(line)
    if value is None:
        return None
    quarters = value * 4
    if quarters != quarters.to_integral_value():
        return None
    q = int(quarters)
    if q % 4 == 0:
        return "whole"
    if q % 2 != 0:
        return "quarter"
    return "half"


def _straight(value: Decimal, line: Decimal, op: str) -> Decimal:
    """Uma linha inteira ou meia contra um valor. +1 ganhou, 0 devolveu, -1 perdeu."""
    if op == "over":
        if value > line:
            return _ONE
        if value < line:
            return -_ONE
        return _ZERO
    if value < line:
        return _ONE
    if value > line:
        return -_ONE
    return _ZERO


def _apply_grid(value: Decimal, line: Decimal, op: str, grid: str) -> Decimal:
    if grid == "quarter":
        return (_straight(value, line - _QUARTER, op)
                + _straight(value, line + _QUARTER, op)) / 2
    return _straight(value, line, op)


###############################################################################
# Over / Under (gols, escanteios, cartoes, faltas, chutes, impedimentos...)
###############################################################################
def settle_over_under(value, line, op) -> tuple[str | None, Decimal]:
    """Liquida um mercado de total. `value` None (estatistica ausente) -> UNRESOLVED.

    Funciona pra qualquer contador inteiro; quem escolhe QUAL contador entra
    aqui e' o chamador. Nao arredonda nem trunca o valor observado: 10
    escanteios entram como Decimal("10") e sao comparados exatamente contra
    Decimal("9.5").
    """
    if op not in ("over", "under"):
        return UNRESOLVED
    v = to_decimal(value)
    ln = to_decimal(line)
    if v is None or ln is None:
        return UNRESOLVED
    grid = line_grid(ln)
    if grid is None:
        return UNRESOLVED
    factor = _apply_grid(v, ln, op, grid)
    return _FACTOR_TO_RESULT[factor], factor


def settle_over_under_com_piso(value, line, op, piso=None) -> tuple[str | None, Decimal]:
    """Como settle_over_under, mas aceita um PISO quando o total exato e'
    desconhecido -- e liquida so' quando o piso ja' decide sozinho.

    ## O problema que isto resolve

    A folha da API-Football omite a linha "Red Cards" quando nenhum time levou
    vermelho. O coletor grava NULL (correto: ausencia nunca vira zero,
    invariante 1 acima), e `total_cards = amarelos + 2*vermelhos` fica None.
    Resultado medido em 2026-08-14: 21,3% das partidas encerradas -- 40 de 66
    so' em agosto -- ficavam com QUALQUER mercado de cartao impossivel de
    liquidar, e uma alavancagem de 13/08 estava presa por isso.

    ## Por que o piso e' seguro, e nao um chute

    Vermelho nunca e' negativo. Entao, sem saber quantos foram:

        total_de_cartoes >= total_de_amarelos

    Com 3 amarelos, um "Over 2.5" ja' esta' ganho -- descobrir depois que
    houve 1 vermelho leva o total pra 5 e nao muda nada. A conclusao NAO
    depende do numero que falta, e por isso nao e' inferencia: e' o mesmo
    raciocinio que o motor Live ja' usa pra recusar "linha ja batida pelo
    placar atual".

    O piso decide em exatamente dois casos, os dois pelo mesmo motivo
    (o desconhecido so' pode SOMAR ao total):

        over  com piso > linha  -> GREEN   (ja passou; o resto so' aumenta)
        under com piso > linha  -> RED     (ja estourou; o resto so' aumenta)

    Em qualquer outro caso o desconhecido ainda muda o veredito, e a funcao
    devolve UNRESOLVED -- que e' o comportamento de sempre. Nenhum caso que
    hoje liquida passa a liquidar diferente: com `value` conhecido, o piso
    nem e' olhado.
    """
    resultado = settle_over_under(value, line, op)
    if resultado[0] is not None or piso is None:
        return resultado

    if op not in ("over", "under"):
        return UNRESOLVED
    p = to_decimal(piso)
    ln = to_decimal(line)
    if p is None or ln is None or line_grid(ln) is None:
        return UNRESOLVED
    if p <= ln:
        # O que falta ainda pode virar o resultado -- nao ha o que afirmar.
        return UNRESOLVED
    return (GREEN, _ONE) if op == "over" else (RED, -_ONE)


###############################################################################
# Handicap asiatico (gols, escanteios, cartoes)
###############################################################################
def settle_asian_handicap(side, handicap, home_value, away_value) -> tuple[str | None, Decimal]:
    """Handicap aplicado ao lado apostado. side "home"/"away"; sem lado -> UNRESOLVED.

    Mesma divisao de quarto-de-bola do over/under: a vantagem/desvantagem
    entra como deslocamento do proprio placar, e a comparacao final e' contra
    o adversario.
    """
    if side not in ("home", "away"):
        return UNRESOLVED
    h = to_decimal(handicap)
    hv = to_decimal(home_value)
    av = to_decimal(away_value)
    if h is None or hv is None or av is None:
        return UNRESOLVED
    grid = line_grid(h)
    if grid is None:
        return UNRESOLVED

    own, opponent = (hv, av) if side == "home" else (av, hv)

    def straight(adjust: Decimal) -> Decimal:
        return _straight(own + adjust, opponent, "over")

    if grid == "quarter":
        factor = (straight(h - _QUARTER) + straight(h + _QUARTER)) / 2
    else:
        factor = straight(h)
    return _FACTOR_TO_RESULT[factor], factor


###############################################################################
# Mercados de resultado
###############################################################################
_OUTCOME_ALIASES = {
    "1": "1", "casa": "1", "mandante": "1", "home": "1",
    "x": "x", "empate": "x", "draw": "x", "e": "x",
    "2": "2", "visitante": "2", "away": "2", "fora": "2", "visita": "2",
}

_DOUBLE_CHANCE = {
    "1x": {"1", "x"}, "x1": {"1", "x"},
    "12": {"1", "2"}, "21": {"1", "2"},
    "x2": {"x", "2"}, "2x": {"x", "2"},
    "casaempate": {"1", "x"}, "empatecasa": {"1", "x"},
    "empatevisitante": {"x", "2"}, "visitanteempate": {"x", "2"},
    "casavisitante": {"1", "2"}, "visitantecasa": {"1", "2"},
    "casafora": {"1", "2"}, "foracasa": {"1", "2"},
    "homedraw": {"1", "x"}, "drawhome": {"1", "x"},
    "drawaway": {"x", "2"}, "awaydraw": {"x", "2"},
    "homeaway": {"1", "2"}, "awayhome": {"1", "2"},
}


def _normalize_selection(text: str) -> str:
    """Forma canonica de uma selecao de resultado: 'Draw / Away' e 'Empate ou
    Visitante' viram 'drawaway' e 'empatevisitante'."""
    out = (text or "").strip().lower()
    for token in (" ", "/", "-", "+", "ou"):
        out = out.replace(token, "")
    return out


def actual_outcome(home_goals, away_goals) -> str | None:
    hg, ag = to_decimal(home_goals), to_decimal(away_goals)
    if hg is None or ag is None:
        return None
    if hg > ag:
        return "1"
    if hg < ag:
        return "2"
    return "x"


def settle_outcome(home_goals, away_goals, line,
                   home_team: str | None = None,
                   away_team: str | None = None) -> tuple[str | None, Decimal]:
    """1X2 e Dupla Chance. Linha nao reconhecida -> UNRESOLVED (nunca RED).

    A selecao sai SO' da linha, nunca do nome do mercado. A versao anterior
    tambem procurava as chaves de dupla chance dentro do nome do mercado, e
    "Resultado Final (1X2)" contem o texto "1x" -- entao todo pick de 1X2
    virava um "1 ou X" e era gravado GREEN em empate, qualquer que fosse a
    selecao real. Casamento aqui e' exato sobre a forma canonica, nao
    substring.
    """
    actual = actual_outcome(home_goals, away_goals)
    if actual is None:
        return UNRESOLVED

    ln = (str(line or "")).strip().lower()
    compact = _normalize_selection(ln)

    # Nome do time no lugar do codigo ("Fortaleza EC" em vez de "1")
    if home_team and home_team.strip() and ln == home_team.strip().lower():
        return (GREEN, _ONE) if actual == "1" else (RED, -_ONE)
    if away_team and away_team.strip() and ln == away_team.strip().lower():
        return (GREEN, _ONE) if actual == "2" else (RED, -_ONE)

    # Dupla chance escrita com o nome do time ("Fortaleza EC ou Empate")
    for team, code in ((home_team, "1"), (away_team, "2")):
        if not team or not team.strip():
            continue
        team_compact = _normalize_selection(team)
        if not team_compact or team_compact not in compact:
            continue
        rest = compact.replace(team_compact, "", 1)
        if rest in ("empate", "draw", "x"):
            return (GREEN, _ONE) if actual in (code, "x") else (RED, -_ONE)

    valid = _DOUBLE_CHANCE.get(compact)
    if valid is not None:
        return (GREEN, _ONE) if actual in valid else (RED, -_ONE)

    predicted = _OUTCOME_ALIASES.get(compact)
    if predicted is None:
        return UNRESOLVED
    return (GREEN, _ONE) if predicted == actual else (RED, -_ONE)


def settle_btts(home_goals, away_goals, op) -> tuple[str | None, Decimal]:
    """Ambas marcam. op "yes"/"no"; qualquer outra coisa -> UNRESOLVED."""
    if op not in ("yes", "no"):
        return UNRESOLVED
    hg, ag = to_decimal(home_goals), to_decimal(away_goals)
    if hg is None or ag is None:
        return UNRESOLVED
    both = hg > 0 and ag > 0
    won = both if op == "yes" else not both
    return (GREEN, _ONE) if won else (RED, -_ONE)


###############################################################################
# Dinheiro
###############################################################################
def profit_units(factor, odd) -> Decimal | None:
    """Lucro por 1 unidade apostada. Mesma tabela usada pelo painel do usuario
    (website/backend/routers/banca.py::_compute_follow_pnl)."""
    f = to_decimal(factor)
    o = to_decimal(odd)
    if f is None or o is None:
        return None
    if f == _ONE:
        return o - _ONE
    if f == _HALF:
        return (o - _ONE) / 2
    if f == _ZERO:
        return _ZERO
    if f == -_HALF:
        return -_HALF
    return -_ONE


def leg_payout_factor(result: str | None, odd) -> Decimal | None:
    """Quanto 1 unidade apostada nesta perna VOLTA (nao o lucro).

    GREEN -> odd | PUSH -> 1 (stake devolvida) | RED -> 0
    HALF-WIN -> (1 + odd) / 2 | HALF-LOSS -> 0.5

    E' o que permite combinar pernas de bilhete sem inventar regra: o retorno
    de uma multipla e' o produto dos retornos das pernas.
    """
    o = to_decimal(odd)
    if result is None or o is None:
        return None
    if result == GREEN:
        return o
    if result == PUSH:
        return _ONE
    if result == RED:
        return _ZERO
    if result == HALF_WIN:
        return (_ONE + o) / 2
    if result == HALF_LOSS:
        return _HALF
    return None


def combine_legs(leg_results, leg_odds,
                 ticket_odd=None) -> tuple[str | None, Decimal | None, Decimal | None]:
    """Liquida um bilhete combinado. Devolve (label, lucro_em_unidades, odd_efetiva).

    Perna pendente (None) -> (None, None, None): bilhete continua em aberto.

    `ticket_odd` e' a odd combinada publicada no pick (total_odd /
    odd_combined) -- e' ela que manda quando todas as pernas batem GREEN,
    porque e' a odd que o usuario de fato pegou; o produto das odds das
    pernas so' serve de fallback quando ela nao vem. Perna que NAO deu GREEN
    entra como ajuste sobre essa odd (fator da perna dividido pela odd da
    perna), que e' como uma casa recalcula o bilhete.

    Uma perna PUSH NAO derruba o bilhete -- ela sai da conta com fator 1, que
    e' como qualquer casa liquida uma perna anulada. As duas implementacoes
    antigas erravam isso em direcoes opostas: o job em lote convertia PUSH e
    HALF-* em RED (ai_result_checker_multiplas.evaluate_leg), matando um
    bilhete que na pratica ainda podia pagar; o caminho ao vivo devolvia PUSH
    pro bilhete inteiro (_multipla_combined_result) sempre que houvesse
    mistura, zerando um bilhete que na pratica tinha lucro.
    """
    results = list(leg_results)
    odds = [to_decimal(o) for o in leg_odds]
    if not results or len(results) != len(odds):
        return None, None, None
    if any(r is None for r in results):
        return None, None, None
    if any(r not in RESULT_LABELS for r in results):
        return None, None, None

    if any(r == RED for r in results):
        return RED, -_ONE, _ZERO

    base = to_decimal(ticket_odd)
    if base is None or base <= _ZERO:
        base = _ONE
        for odd in odds:
            if odd is None:
                return None, None, None
            base *= odd

    payout = base
    for result, odd in zip(results, odds):
        if result == GREEN:
            continue  # ja embutida na odd combinada publicada
        if odd is None or odd <= _ZERO:
            return None, None, None
        factor = leg_payout_factor(result, odd)
        if factor is None:
            return None, None, None
        payout = payout * factor / odd

    profit = payout - _ONE
    if profit > _ZERO:
        label = GREEN
    elif profit == _ZERO:
        label = PUSH
    elif profit == -_HALF:
        label = HALF_LOSS
    else:
        label = RED
    return label, profit, payout
