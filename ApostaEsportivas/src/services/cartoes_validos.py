"""Quantos cartoes CONTAM pro mercado -- que nao e' o numero da folha.

## O problema

`/fixtures/statistics` publica "Yellow Cards" por time, e esse contador soma
TUDO que o arbitro tirou do bolso: jogador em campo, jogador no banco, tecnico,
auxiliar e preparador. A casa nao liquida assim. O mercado de cartoes e' sobre
jogadores em campo, e um amarelo pro tecnico na area tecnica e' exatamente a
diferenca entre GREEN e RED num "Over 7.5".

O numero bruto nao e' corrigivel depois: ele chega ja' somado, sem dizer quem
levou. Quem sabe quem levou e' `/fixtures/events`, e quem sabe se essa pessoa
estava em campo naquele minuto e' `/fixtures/lineups` mais a ordem das
substituicoes. Este modulo junta as tres coisas e devolve a contagem elegivel.

## O que ele NAO faz

Nao chuta. Quando falta escalacao, ele nao "assume que estava em campo" -- diz
`INCERTO` e devolve a lista do que nao deu pra verificar, e quem liquida trata
isso como nao liquidado (services/settlement.py, invariante 1: ausencia nunca
vira numero). Um cartao contado errado nao produz so' um total errado, produz
um GREEN falso -- que e' pior que um pick pendente.

## Por que a substituicao e' resolvida por PERTENCIMENTO, e nao pelo campo

Em `/fixtures/events` o evento `subst` traz duas pessoas (`player` e `assist`)
e a documentacao da API-Football nao e' confiavel sobre qual das duas entrou.
Chutar a direcao erraria justamente o caso que este modulo existe pra pegar.
Entao a direcao nao e' lida: das duas pessoas do par, a que ESTA' em campo
naquele instante e' a que saiu, e a outra entrou. Isso parte do `startXI` e nao
depende de convencao nenhuma da API.
"""
from __future__ import annotations

# ── Classificacao de um cartao ───────────────────────────────────────────
EM_CAMPO = "EM_CAMPO"
NO_BANCO = "NO_BANCO"
COMISSAO = "COMISSAO_TECNICA"
NAO_ELEGIVEL = "OUTRO_EVENTO_NAO_ELEGIVEL"
INDETERMINADO = "INDETERMINADO"

VALIDADO = "VALIDADO"
INCERTO = "INCERTO"

_MOTIVO = {
    NO_BANCO: "Jogador estava no banco",
    COMISSAO: "Cartao para comissao tecnica",
    NAO_ELEGIVEL: "Evento nao elegivel para o mercado de cartoes",
    INDETERMINADO: "Sem escalacao: nao da' pra afirmar que estava em campo",
}


def _id(bloco) -> int | None:
    valor = (bloco or {}).get("id")
    try:
        return None if valor is None else int(valor)
    except (TypeError, ValueError):
        return None


def _nome(bloco) -> str | None:
    return ((bloco or {}).get("name") or None)


def _ordem(evento: dict, i: int) -> tuple:
    tempo = evento.get("time") or {}
    minuto = tempo.get("elapsed")
    extra = tempo.get("extra")
    return (minuto if minuto is not None else 10**6, extra or 0, i)


def ler_escalacoes(escalacoes: list | None) -> dict:
    """`/fixtures/lineups` -> por time: titulares, reservas e o tecnico.

    Devolve `{}` quando a escalacao nao veio. Vazio aqui nao e' "time sem
    jogadores", e' "nao perguntei ou nao respondeu" -- e e' o que faz a
    validacao cair em INCERTO em vez de excluir cartao por engano.
    """
    por_time: dict[int, dict] = {}
    for bloco in escalacoes or []:
        tid = _id(bloco.get("team"))
        if tid is None:
            continue
        titulares, reservas = set(), set()
        for item in bloco.get("startXI") or []:
            pid = _id(item.get("player"))
            if pid is not None:
                titulares.add(pid)
        for item in bloco.get("substitutes") or []:
            pid = _id(item.get("player"))
            if pid is not None:
                reservas.add(pid)
        if not titulares:
            # startXI vazio nao serve de base pro rastreio de quem esta' em
            # campo: sem os 11 iniciais toda substituicao fica ambigua.
            continue
        por_time[tid] = {
            "titulares": titulares,
            "reservas": reservas,
            "elenco": titulares | reservas,
            "tecnico": _id(bloco.get("coach")),
        }
    return por_time


def _e_cartao(evento: dict) -> bool:
    return (evento.get("type") or "").strip().lower() == "card"


def _cores(evento: dict) -> tuple[int, int]:
    """Quantos amarelos e quantos vermelhos ESTE evento representa.

    O segundo amarelo conta como os dois, e nao e' escolha nossa: e' assim que
    a folha de `/fixtures/statistics` soma (o jogador aparece com 2 em "Yellow
    Cards" e 1 em "Red Cards") e e' assim que a casa liquida. Ler "Second
    Yellow card" so' como amarelo deixaria o mercado de vermelho sempre em
    zero; ler so' como vermelho perderia um amarelo do total.
    """
    detalhe = (evento.get("detail") or "").lower()
    if "second yellow" in detalhe:
        return 1, 1
    if "red" in detalhe:
        return 0, 1
    return 1, 0


def validar_cartoes(eventos: list | None, escalacoes: list | None = None,
                    home_id=None, away_id=None, total_bruto=None) -> dict:
    """Classifica cartao a cartao e devolve so' o que conta pro mercado.

    `eventos` e `escalacoes` sao as respostas cruas de `/fixtures/events` e
    `/fixtures/lineups`. `total_bruto` e' o numero da folha, quando existir --
    entra so' no relatorio, pra deixar visivel o tamanho da correcao; ele nunca
    e' usado como resultado.

    Sem eventos a funcao nao tem o que classificar e devolve `disponivel:
    False` com as contagens em None -- de novo a invariante 1: lista vazia
    responde igual pra "partida sem cobertura de evento" e pra "ainda nao
    aconteceu nada", e transformar a primeira em zero e' o erro que fabrica
    Under.
    """
    if not eventos:
        return {
            "disponivel": False,
            "status_validacao": INCERTO,
            "confianca": 0.0,
            "total_cartoes_fonte": total_bruto,
            "total_cartoes_validos": None,
            "pontos_validos": None,
            "cartoes_excluidos": None,
            "amarelos_validos": None,
            "vermelhos_validos": None,
            "por_time": {},
            "eventos_excluidos": [],
            "eventos_indeterminados": [],
        }

    try:
        home_id = None if home_id is None else int(home_id)
        away_id = None if away_id is None else int(away_id)
    except (TypeError, ValueError):
        home_id = away_id = None

    elencos = ler_escalacoes(escalacoes)
    #: Quem esta' em campo AGORA, por time. So' existe pra quem tem titular
    #: conhecido -- e' o unico ponto de partida honesto do rastreio.
    em_campo = {tid: set(dados["titulares"]) for tid, dados in elencos.items()}

    ordenados = sorted(enumerate(eventos), key=lambda par: _ordem(par[1], par[0]))

    contagem: dict[str, int] = {}
    excluidos: list[dict] = []
    indeterminados: list[dict] = []

    def _lado(tid):
        if tid is not None and tid == home_id:
            return "home"
        if tid is not None and tid == away_id:
            return "away"
        return None

    for _, evento in ordenados:
        tid = _id(evento.get("team"))
        tipo = (evento.get("type") or "").strip().lower()

        if tipo == "subst":
            if tid in em_campo:
                # DIRECAO RESOLVIDA POR PERTENCIMENTO, nao pelo campo da API:
                # das duas pessoas do par, quem esta' em campo e' quem saiu.
                par = [p for p in (_id(evento.get("player")),
                                   _id(evento.get("assist"))) if p is not None]
                dentro = [p for p in par if p in em_campo[tid]]
                fora = [p for p in par if p not in em_campo[tid]]
                if len(dentro) == 1 and len(fora) == 1:
                    em_campo[tid].discard(dentro[0])
                    em_campo[tid].add(fora[0])
                else:
                    # Par ambiguo (os dois em campo, ou nenhum): o rastreio
                    # deste time deixa de ser confiavel, e todo cartao seguinte
                    # dele cai em INDETERMINADO em vez de ser excluido por
                    # engano.
                    em_campo.pop(tid, None)
            continue

        if not _e_cartao(evento):
            continue

        pid = _id(evento.get("player"))
        amarelos_do_evento, vermelhos_do_evento = _cores(evento)
        lado = _lado(tid)
        registro = {
            "jogador": _nome(evento.get("player")),
            "player_id": pid,
            "time_id": tid,
            "lado": lado,
            "minuto": (evento.get("time") or {}).get("elapsed"),
            "detalhe": (evento.get("detail") or "").strip(),
        }

        elenco = elencos.get(tid)
        if elenco is None:
            classe = INDETERMINADO
        elif pid is None:
            # Cartao sem jogador identificado: a API faz isso justamente com a
            # area tecnica.
            classe = COMISSAO
        elif pid not in elenco["elenco"]:
            # Fora do elenco relacionado: tecnico, auxiliar, preparador.
            classe = COMISSAO
        elif tid not in em_campo:
            classe = INDETERMINADO
        elif pid in em_campo[tid]:
            classe = EM_CAMPO
        else:
            # No elenco, mas nao em campo neste minuto: reserva que nao entrou,
            # ou titular que ja' saiu. Cartao recebido ANTES da substituicao
            # nao cai aqui -- naquele minuto ele ainda estava em `em_campo`.
            classe = NO_BANCO

        if classe == EM_CAMPO and lado is None:
            # Cartao de um time que nao e' nenhum dos dois desta partida.
            classe = NAO_ELEGIVEL

        if classe == EM_CAMPO:
            contagem[f"yellow_{lado}"] = (contagem.get(f"yellow_{lado}", 0)
                                          + amarelos_do_evento)
            contagem[f"red_{lado}"] = (contagem.get(f"red_{lado}", 0)
                                       + vermelhos_do_evento)
            # Expulso sai de campo: o proximo cartao dele, se houver, ja' nao
            # e' de alguem em campo.
            if vermelhos_do_evento and tid in em_campo and pid is not None:
                em_campo[tid].discard(pid)
        elif classe == INDETERMINADO:
            registro["motivo"] = _MOTIVO[INDETERMINADO]
            indeterminados.append(registro)
        else:
            registro["motivo"] = _MOTIVO[classe]
            excluidos.append(registro)

    for lado in ("home", "away"):
        for cor in ("yellow", "red"):
            contagem.setdefault(f"{cor}_{lado}", 0)

    amarelos = contagem["yellow_home"] + contagem["yellow_away"]
    vermelhos = contagem["red_home"] + contagem["red_away"]
    status = INCERTO if indeterminados else VALIDADO

    return {
        "disponivel": True,
        "status_validacao": status,
        # 0.99 e nao 1.0 de proposito: a classificacao esta' certa pro que a
        # API publicou, e a API ainda pode corrigir a sumula depois.
        "confianca": 0.99 if status == VALIDADO else 0.5,
        "total_cartoes_fonte": total_bruto,
        "total_cartoes_validos": amarelos + vermelhos,
        # Convencao de PONTOS do motor (vermelho vale 2), a mesma de
        # stats_model._cards_points e de ai_result_checker_service.total_cards.
        # Fica pronta aqui pra quem liquida nao ter que refazer a conta com
        # outra regra -- gradear com uma e prever com outra e' o erro que
        # deixa o confidence do pick sem relacao com o resultado.
        "pontos_validos": amarelos + 2 * vermelhos,
        "cartoes_excluidos": len(excluidos),
        "amarelos_validos": amarelos,
        "vermelhos_validos": vermelhos,
        "por_time": dict(contagem),
        "eventos_excluidos": excluidos,
        "eventos_indeterminados": indeterminados,
    }
