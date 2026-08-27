"""Leitura da folha de /fixtures/statistics da API-Football.

UM lugar so' pra decidir o que cada valor da folha significa. Antes desta
modulo havia TRES leitores independentes -- collectors/match_statistics_sync_
service.extract_stat, services/historical_api_fetcher.get_stat e
services/pick_engine_live/live_feed._numero -- e os tres discordavam entre si
sobre o caso mais comum da folha inteira: `value: null`.


O QUE A MEDICAO MOSTROU (2026-08-26, 10 partidas FT sorteadas, 20 folhas)

    tipo                     null   zero explicito   >0
    Ball Possession             0                0   20
    Blocked Shots               0                1   19
    Corner Kicks                0                1   19
    Fouls                       0                0   20
    Goalkeeper Saves            0                0   20
    Offsides                    0                4   16
    Shots off Goal              0                1   19
    Yellow Cards                0                1   19
    Red Cards                  18                1    1
    (demais tipos)              0                0   20

A API publica ZERO EXPLICITO em todo contador -- escanteio, falta, impedimento,
chute, amarelo. O UNICO tipo que ela devolve como null e' "Red Cards", e ela
faz isso justamente no caso normal: ninguem foi expulso.

Ou seja: numa folha PUBLICADA, `null` num contador significa ZERO, nao
"desconhecido". Tratar esse null como ausencia foi o que deixou agosto/2026
com 95 jogos FT e apenas 12 com vermelho no banco -- os 12 em que houve
expulsao. Nenhum zero. Os outros 83 viraram NULL e sumiram do pool de cartoes
do motor (stats_model._tem_folha_de_cartao_completa derruba o jogo), o que
custou 87% da amostra de cartoes.


A REGRA, E POR QUE ELA NAO REINTRODUZ O BUG DE 2026-07-25

Aquele bug era o oposto: folha AUSENTE (a API responde com lista vazia) virava
zero em tudo, e o banco guardava 99 jogos FT com escanteio, falta e chute todos
em 0 -- 94 deles com gol, ou seja, jogos que aconteceram de verdade. A
invariante 1 de services/settlement.py nasceu disso.

As duas coisas convivem porque a pergunta e' outra. Aqui se olha a folha
INTEIRA antes de ler qualquer campo:

    folha vazia / so' com nulls   -> nada foi publicado -> TUDO None
    folha publicada, tipo ausente -> aquele contador nao veio -> None
    folha publicada, null no vermelho -> ZERO
    folha publicada, null em outro tipo -> None (ausencia, como antes)
    folha publicada, valor number -> o numero

Ausencia continua nunca virando zero. O que mudou e' que "folha publicada com
null no vermelho" deixou de ser classificado como ausencia -- porque nao e'.

A regra vale so' pra "Red Cards" -- ver `_VAZIO_E_ZERO`. Em qualquer outro
tipo, `null` continua sendo ausencia, do mesmo jeito que era antes.
"""

#: Os UNICOS tipos em que `null` dentro de folha publicada significa ZERO.
#:
#: A lista e' curta de proposito. Poderia ser "todo contador", ja' que a regra
#: e' a mesma -- mas so' o vermelho foi MEDIDO se comportando assim, e a
#: assimetria de risco nao permite generalizar por elegancia: se um dia a API
#: passar a mandar `null` em escanteio pra dizer "ainda nao publiquei", a regra
#: ampla fabrica um zero e o zero fabricado vira pick errado (invariante 1 de
#: services/settlement.py). A regra estreita, no pior caso, so' perde um
#: numero -- que e' exatamente o que ja acontece hoje.
#:
#: Pra incluir um tipo novo aqui: medir primeiro, como esta' no cabecalho.
_VAZIO_E_ZERO = {"Red Cards"}


def folha_publicada(stats) -> bool:
    """A API publicou a folha deste time?

    Basta UM valor preenchido. Folha vazia (`[]`, o caso de jogo sem
    estatistica) e folha so' de nulls (stub) sao as duas formas de "nao
    publicou", e nas duas nada aqui dentro pode virar numero.
    """
    if not stats:
        return False
    return any(item.get("value") is not None for item in stats)


def _para_numero(valor):
    """Converte o valor cru da folha. None quando nao da' pra ler."""
    if isinstance(valor, str):
        valor = valor.replace("%", "").strip()
        if not valor:
            return None
        try:
            return float(valor)
        except ValueError:
            return None
    if isinstance(valor, bool):      # a API nunca manda, mas bool e' int em Python
        return None
    if isinstance(valor, (int, float)):
        return valor
    return None


def ler_valor(stats, tipo: str, publicada: bool | None = None):
    """Valor do contador `tipo`, ou None quando de fato nao se sabe.

    `publicada` evita re-varrer a folha quando o chamador ja' a classificou
    (o coletor le ~20 tipos da mesma folha).
    """
    if publicada is None:
        publicada = folha_publicada(stats)
    if not publicada:
        return None

    for item in stats:
        if item.get("type") != tipo:
            continue
        bruto = item.get("value")
        if bruto is None:
            # Folha publicada + campo vazio = zero. Ver o cabecalho: e' assim
            # que a API escreve "ninguem foi expulso".
            return 0 if tipo in _VAZIO_E_ZERO else None
        return _para_numero(bruto)

    # O tipo nem aparece na folha: esse contador realmente nao veio.
    return None


def ler_folha(stats) -> dict:
    """A folha inteira como {tipo: numero}, ja' com a regra aplicada.

    Diferente de `ler_valor` num laco so' no desempenho: classifica a folha
    uma vez. Tipos ilegiveis ficam de fora do dicionario, e ausencia continua
    representada por ausencia da chave.
    """
    if not folha_publicada(stats):
        return {}
    lida: dict = {}
    for item in stats:
        tipo = item.get("type")
        if tipo is None:
            continue
        bruto = item.get("value")
        if bruto is None:
            if tipo not in _VAZIO_E_ZERO:
                continue          # ausencia continua sendo ausencia
            lida[tipo] = 0
            continue
        numero = _para_numero(bruto)
        if numero is not None:
            lida[tipo] = numero
    return lida


def somar(*parcelas):
    """Total que respeita ausencia: parcela desconhecida -> total desconhecido."""
    return None if any(p is None for p in parcelas) else sum(parcelas)
