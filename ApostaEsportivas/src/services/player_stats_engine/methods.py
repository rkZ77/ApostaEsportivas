"""Catalogo de METODOS do Player Stats -- uma estatistica individual cada.

ESTE ARQUIVO E' A ARQUITETURA
-----------------------------
Acrescentar um mercado de jogador (cruzamentos, impedimentos, cartao) e'
acrescentar UM `Metodo` nesta tupla: coluna de onde o numero sai, nomes do
mercado nas casas, amostra minima e a leitura em PT. O motor, a calibragem, a
probabilidade, o Score, a auditoria e a liquidacao ja' funcionam pra qualquer
metodo declarado aqui -- nao ha' um pipeline por mercado.

Era exatamente o que faltava: "defesas de goleiro" era um MOTOR inteiro
(goleiros_pipeline.py, 30 KB) pra um contador so'. A partir de 27/08 ele e' um
metodo, e o codigo medido dele (goalkeeper_model + saves_calibration) continua
sendo a funcao de valor esperado desse metodo, sem uma linha alterada.

O QUE E' `mando_do_adversario`
------------------------------
Alguns contadores dependem do ADVERSARIO, nao do jogador. Defesa de goleiro e'
o caso extremo: a correlacao com chutes no alvo sofridos e' 0.88, e o
historico pessoal do goleiro e' o sinal fraco. Outros (passes, desarmes) sao
majoritariamente do proprio jogador. A flag diz de qual lado o motor pega o
volume; errar esse lado inverte a previsao, e por isso ela e' declarada e nao
inferida.

QUAIS RODAM TODO DIA (2026-08-28)
---------------------------------
`saves`, `shots_on` e `shots` -- decisao do usuario. Sao os tres contadores com
mercado liquido nas casas e frequencia alta o suficiente pra produzir pick:
chute aparece em toda atuacao, chute no alvo na maioria, e defesa e' o metodo
ja' medido (correlacao 0.88 com chutes no alvo sofridos).

`fouls`, `tackles` e `passes` ficam de fora ate' gerarem pick real e serem
medidos. Nao e' esquecimento: e' o mesmo criterio que manteve o Pick Boost fora
do `tudo` ate' ele ser publicado.

A marca vive no CATALOGO (`Metodo.diario`) e nao numa lista em main.py -- ver o
comentario do campo.

AMOSTRA E CARGO
---------------
`min_atuacoes` e' por metodo porque as frequencias sao muito diferentes: uma
defesa aparece em 0.86% das atuacoes medidas e um passe aparece em todas.
Exigir o mesmo numero nos dois zeraria uns e afrouxaria outros.

PISO DE 4 (2026-08-28, decisao do usuario). Os valores eram 3 a 6 e passaram a
4 em todos: piso unico de amostra pra todos os pipelines e todos os tipos de
pick. O campo CONTINUA sendo por metodo -- e' ele que permite subir de novo o de
um contador especifico quando houver medicao pedindo, sem mexer nos outros.

Aqui o piso morde mais que no resto do motor: atuacao so' conta com 60+ minutos
(player_history.MIN_MINUTOS), entao 4 atuacoes sao 4 jogos de titular efetivo, e
nao 4 aparicoes.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Metodo:
    slug: str
    label: str
    #: Coluna de `player_match_stats` que conta o evento.
    coluna: str
    #: Nomes do mercado nas casas, minusculos. O market_id varia por casa,
    #: entao o casamento e' por nome -- mesmo padrao de faltas e goleiros.
    nomes_mercado: frozenset
    #: Minimo de atuacoes do jogador com o contador publicado.
    min_atuacoes: int
    #: Minimo de jogos do adversario, quando o metodo depende dele.
    min_amostra_adversario: int = 0
    #: De qual lado vem o volume que empurra o contador.
    depende_do_adversario: bool = False
    #: Coluna de `match_statistics` que mede esse volume do adversario.
    coluna_do_adversario: str | None = None
    #: Nome da familia em `pick_engine/tie_effect`, quando difere do slug.
    #:
    #: Existe porque as duas listas nasceram separadas: o tie_effect fala
    #: "shots_on_target" e o catalogo fala "shots_on". Enquanto defesas era um
    #: motor proprio, a traducao vivia escrita a mao no pipeline dele -- e foi
    #: assim que ela se perdeu na migracao de 27/08, junto com a chamada
    #: inteira. Aqui ela e' um campo do metodo: acrescentar mercado continua
    #: sendo acrescentar UM `Metodo`.
    #:
    #: Vazio = o slug ja e' o nome da familia.
    familia_contexto: str = ""
    #: Posicoes elegiveis (vazio = todas). "G" e' goleiro.
    posicoes: frozenset = field(default_factory=frozenset)
    #: Rotulo do mercado em PT, pro texto do pick e da tela.
    rotulo_linha: str = "{n} ou mais"
    #: Roda no pipeline diario (`main.py tudo`)?
    #:
    #: FICA NO CATALOGO, e nao numa lista solta em main.py, pelo mesmo motivo
    #: que todo o resto: acrescentar um mercado e' acrescentar UM `Metodo`. Se a
    #: lista do pipeline vivesse fora, promover um metodo exigiria lembrar de
    #: dois lugares -- e o segundo e' o que se esquece.
    #:
    #: Metodo novo nasce FALSE: ele so' entra na rodada diaria depois de gerar
    #: pick de verdade e ser medido. Ate' la' roda na mao, com `playerstats
    #: <slug>`.
    diario: bool = False
    #: Dispersao congelada, usada so' quando a recalibragem nao tem amostra.
    #: Comeca em 1.0 (= Poisson) de proposito nos metodos que ainda nao foram
    #: medidos: e' o valor neutro, e a calibragem mede na propria base a cada
    #: rodada. Chutar um phi alto "por seguranca" desloca probabilidade sem
    #: nenhuma medicao atras.
    phi_congelado: float = 1.0


#: Defesas de goleiro -- o antigo motor de goleiros. Nao tem `phi_congelado`
#: neutro porque este e' o unico metodo JA' MEDIDO: 3.19 em 01/08, contra 946
#: jogos, e a recalibragem por rodada continua existindo em saves_calibration.
def familia_do_contexto(metodo: "Metodo") -> str:
    """Nome que o `tie_effect` entende pra este metodo."""
    return metodo.familia_contexto or metodo.slug


SAVES = Metodo(
    slug="saves", label="Defesas de goleiro", coluna="saves",
    nomes_mercado=frozenset({"goalkeeper saves", "goalkeeper saves over/under",
                             "player saves", "saves"}),
    min_atuacoes=4, min_amostra_adversario=4,
    depende_do_adversario=True, coluna_do_adversario="shots_on",
    posicoes=frozenset({"G"}),
    rotulo_linha="{n} ou mais defesas", phi_congelado=3.19,
    diario=True,
)

SHOTS_ON = Metodo(
    slug="shots_on", label="Chutes no alvo", coluna="shots_on",
    familia_contexto="shots_on_target",
    nomes_mercado=frozenset({"player shots on target", "shots on target",
                             "player shots on goal", "shots on target by player",
                             # POR LADO (2026-09-04). A Bet365 parou de publicar
                             # o mercado 242 ("Player Shots On Target", os dois
                             # times numa lista so') e passou a publicar 269/275,
                             # um por mando. Sao as MESMAS ofertas, no mesmo
                             # formato de value_name ("Fulano - 2"); so' o nome
                             # do mercado mudou. Sem estes quatro nomes o motor
                             # jogava fora 968 ofertas de chute no alvo num dia
                             # so' e registrava "nenhuma casa ofereceu mercado".
                             "home player shots on target total",
                             "away player shots on target total",
                             "home player shots on target",
                             "away player shots on target"}),
    min_atuacoes=4,
    rotulo_linha="{n} ou mais chutes no alvo",
    diario=True,
)

SHOTS = Metodo(
    slug="shots", label="Chutes", coluna="shots_total",
    # "home/away player shots" e' o par de 240/241, o mesmo desdobramento por
    # mando descrito em SHOTS_ON.
    #
    # "home/away player shots TOTAL" (276 e o par dele) fica DE FORA de
    # proposito: apesar do nome quase igual, e' o total de chutes do TIME,
    # publicado pela Betano como "Over 3.5" e nao como "Fulano - 3". Nao e' prop
    # de jogador -- e o `parse_valor` ja' descartaria a linha, mas o mercado
    # ainda contaria como oferecido e mentiria na auditoria.
    nomes_mercado=frozenset({"player shots", "total shots by player",
                             "player total shots", "shots",
                             "home player shots", "away player shots"}),
    min_atuacoes=4,
    rotulo_linha="{n} ou mais chutes",
    diario=True,
)

FOULS = Metodo(
    slug="fouls", label="Faltas cometidas", coluna="fouls_committed",
    nomes_mercado=frozenset({"player fouls committed", "fouls committed",
                             "player fouls"}),
    min_atuacoes=4,
    rotulo_linha="{n} ou mais faltas",
)

TACKLES = Metodo(
    slug="tackles", label="Desarmes", coluna="tackles_total",
    nomes_mercado=frozenset({"player tackles", "tackles", "player tackles made"}),
    min_atuacoes=4,
    rotulo_linha="{n} ou mais desarmes",
)

PASSES = Metodo(
    slug="passes", label="Passes", coluna="passes_total",
    nomes_mercado=frozenset({"player passes", "passes", "total passes by player",
                             "player total passes"}),
    # Passe tem media alta (dezenas por jogo) e variancia proporcionalmente
    # menor -- amostra curta ja' estima bem a media, mas a linha do mercado e'
    # alta e um jogo de substituicao (20 minutos) desloca muito. O filtro de
    # minutos em player_history e' o que segura isso; a amostra so' acompanha.
    min_atuacoes=4,
    rotulo_linha="{n} ou mais passes",
)

METODOS: tuple = (SAVES, SHOTS_ON, SHOTS, FOULS, TACKLES, PASSES)

POR_SLUG = {m.slug: m for m in METODOS}

#: Todas as colunas que o motor le de player_match_stats, numa lista so' --
#: e' o SELECT do player_history.
COLUNAS = tuple(dict.fromkeys(m.coluna for m in METODOS))


#: Os que rodam no `tudo`. Ver `Metodo.diario`.
DIARIOS: tuple = tuple(m for m in METODOS if m.diario)


def de(slug: str) -> Metodo | None:
    return POR_SLUG.get(slug)
