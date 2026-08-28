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


FOLHA ROBUSTA: O CONTADOR QUE FALTA NUMA FOLHA CHEIA E' ZERO (2026-08-28)

Pedido do usuario, olhando o diagnostico do /admin: "ele nao coloca 0 quando
vem da API vazio, ele coloca vazio, onde fode tudo". E o diagnostico dava razao
a ele -- de 1.809 jogos, 30 sem escanteio, 45 sem falta, 49 sem chute, 51 sem
defesa. Numeros DIFERENTES por familia, o que descarta "a folha nao veio" (ali
todos seriam iguais): a folha veio, e um contador especifico faltou.

A regra estreita de 26/08 tratava isso como ausencia, e o custo e' concreto:
`stats_model._tem_folha_da_familia` derruba o jogo do pool daquela familia, e a
media do time sai de uma amostra menor sem ninguem saber por que.

O QUE MUDA, E O QUE NAO PODE MUDAR

Nao da' pra generalizar "null vira zero", e o motivo esta' escrito acima: era
exatamente isso que produzia o bug de 2026-07-25 (folha ausente virando zero em
tudo, 99 jogos FT com escanteio/falta/chute zerados, 94 deles COM GOL).

A diferenca entre os dois casos e' EVIDENCIA, e da' pra medir. Uma folha com
quinze contadores preenchidos e um faltando e' uma folha que a API publicou: o
contador que falta e' zero, porque a API nao omite evento que aconteceu. Uma
folha vazia, ou com um contador so', nao autoriza conclusao nenhuma.

    folha nao publicada            -> TUDO None                (inalterado)
    folha publicada mas MAGRA      -> ausencia continua None    (inalterado)
    folha publicada e ROBUSTA      -> contador de EVENTO ausente = 0   <- novo
    percentual ausente             -> None, sempre              (novo, explicito)

PERCENTUAL NUNCA VIRA ZERO. Posse de bola 0% e precisao de passe 0% sao
impossiveis num jogo que aconteceu -- se o campo faltou, faltou mesmo. Zero ali
nao seria um zero conservador, seria um numero inventado que entra direto na
media. E' a unica familia em que o erro nao tem lado seguro.
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

#: Tipos em que ausencia NUNCA pode virar zero, nem em folha robusta.
#:
#: Posse 0% e precisao de passe 0% sao impossiveis num jogo que aconteceu. Nas
#: contagens, zero e' um valor legitimo (o jogo pode ter tido zero impedimento);
#: aqui nao e', e por isso a folha robusta nao os alcanca.
_NUNCA_ZERO = {"Ball Possession", "Passes %"}

#: Quantos contadores numericos fazem uma folha ser ROBUSTA.
#:
#: Cinco e' o mesmo numero que o /admin ja' usa pra chamar uma folha de completa
#: (_COLUNAS_DA_FOLHA em routers/admin.py: escanteio, amarelo, vermelho, falta e
#: chute). Nao e' coincidencia escolhida: e' a definicao que o projeto ja' tinha
#: e que sobreviveu a duas auditorias.
#:
#: Uma folha com cinco contadores de verdade nao e' um stub, e um sexto tipo
#: faltando nela e' evento que nao aconteceu -- nao coleta pela metade.
MIN_CONTADORES_ROBUSTA = 5


def folha_publicada(stats) -> bool:
    """A API publicou a folha deste time?

    Basta UM valor preenchido. Folha vazia (`[]`, o caso de jogo sem
    estatistica) e folha so' de nulls (stub) sao as duas formas de "nao
    publicou", e nas duas nada aqui dentro pode virar numero.
    """
    if not stats:
        return False
    return any(item.get("value") is not None for item in stats)


def folha_robusta(stats, minimo: int = MIN_CONTADORES_ROBUSTA) -> bool:
    """A folha tem contador numerico suficiente pra o que FALTA nela ser zero?

    Ver o cabecalho. A pergunta e' de EVIDENCIA: uma folha com quinze
    contadores e um faltando foi publicada de verdade; uma com um so' nao
    autoriza conclusao sobre os outros.
    """
    if not stats:
        return False
    numericos = sum(1 for item in stats if _para_numero(item.get("value")) is not None)
    return numericos >= minimo


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


def ler_valor(stats, tipo: str, publicada: bool | None = None,
              robusta: bool | None = None):
    # `robusta=False` explicito e' o caminho do jogo EM ANDAMENTO · ver a
    # docstring de `ler_folha` pro porque a mesma folha significa coisas
    # opostas antes e depois do apito.
    """Valor do contador `tipo`, ou None quando de fato nao se sabe.

    `publicada` e `robusta` evitam re-varrer a folha quando o chamador ja' a
    classificou -- o coletor le ~20 tipos da mesma folha, e as duas
    classificacoes sao sobre a folha inteira, nao sobre o tipo.
    """
    if publicada is None:
        publicada = folha_publicada(stats)
    if not publicada:
        return None
    if robusta is None:
        robusta = folha_robusta(stats)

    # Ausencia numa folha ROBUSTA e' zero · menos nos percentuais, onde zero e'
    # impossivel e portanto seria numero inventado. Ver o cabecalho.
    ausente = 0 if (robusta and tipo not in _NUNCA_ZERO) else None

    for item in stats:
        if item.get("type") != tipo:
            continue
        bruto = item.get("value")
        if bruto is None:
            # Vermelho e' zero mesmo em folha magra: foi MEDIDO se comportando
            # assim (ver o cabecalho). Os outros dependem da folha ser robusta.
            return 0 if tipo in _VAZIO_E_ZERO else ausente
        return _para_numero(bruto)

    # O tipo nem aparece na folha.
    return ausente


def ler_folha(stats, jogo_encerrado: bool = True) -> dict:
    """A folha inteira como {tipo: numero}, ja' com a regra aplicada.

    Diferente de `ler_valor` num laco so' no desempenho: classifica a folha
    uma vez. Tipos ilegiveis ficam de fora do dicionario, e ausencia continua
    representada por ausencia da chave.

    `jogo_encerrado=False` DESLIGA a regra da folha robusta, e essa distincao e'
    a mais importante deste modulo depois da propria invariante:

        jogo ENCERRADO   contador que falta = evento que nao aconteceu = 0
        jogo EM ANDAMENTO contador que falta = o provedor ainda nao publicou

    A mesma folha incompleta significa coisas opostas nos dois casos. Ao vivo,
    tratar ausencia como zero destruiria a deteccao de dado atrasado do motor
    Live (`live_state.DELAYED`), que existe justamente pra perceber que o
    provedor parou de atualizar -- e um Over de escanteio decidido em cima de
    "zero escanteios aos 60'" seria pick tomado com dado que nao existe.
    """
    if not folha_publicada(stats):
        return {}
    robusta = jogo_encerrado and folha_robusta(stats)
    lida: dict = {}
    for item in stats:
        tipo = item.get("type")
        if tipo is None:
            continue
        bruto = item.get("value")
        if bruto is None:
            if tipo in _VAZIO_E_ZERO or (robusta and tipo not in _NUNCA_ZERO):
                lida[tipo] = 0
            # senao: ausencia continua sendo ausencia (chave fora do dict)
            continue
        numero = _para_numero(bruto)
        if numero is not None:
            lida[tipo] = numero
    return lida


def somar(*parcelas):
    """Total que respeita ausencia: parcela desconhecida -> total desconhecido."""
    return None if any(p is None for p in parcelas) else sum(parcelas)
