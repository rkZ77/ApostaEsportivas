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

AMOSTRA E CARGO
---------------
`min_atuacoes` e' por metodo porque as frequencias sao muito diferentes: uma
defesa aparece em 0.86% das atuacoes medidas e um passe aparece em todas.
Exigir o mesmo numero nos dois zeraria uns e afrouxaria outros.
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
    #: Posicoes elegiveis (vazio = todas). "G" e' goleiro.
    posicoes: frozenset = field(default_factory=frozenset)
    #: Rotulo do mercado em PT, pro texto do pick e da tela.
    rotulo_linha: str = "{n} ou mais"
    #: Dispersao congelada, usada so' quando a recalibragem nao tem amostra.
    #: Comeca em 1.0 (= Poisson) de proposito nos metodos que ainda nao foram
    #: medidos: e' o valor neutro, e a calibragem mede na propria base a cada
    #: rodada. Chutar um phi alto "por seguranca" desloca probabilidade sem
    #: nenhuma medicao atras.
    phi_congelado: float = 1.0


#: Defesas de goleiro -- o antigo motor de goleiros. Nao tem `phi_congelado`
#: neutro porque este e' o unico metodo JA' MEDIDO: 3.19 em 01/08, contra 946
#: jogos, e a recalibragem por rodada continua existindo em saves_calibration.
SAVES = Metodo(
    slug="saves", label="Defesas de goleiro", coluna="saves",
    nomes_mercado=frozenset({"goalkeeper saves", "goalkeeper saves over/under",
                             "player saves", "saves"}),
    min_atuacoes=3, min_amostra_adversario=5,
    depende_do_adversario=True, coluna_do_adversario="shots_on",
    posicoes=frozenset({"G"}),
    rotulo_linha="{n} ou mais defesas", phi_congelado=3.19,
)

SHOTS_ON = Metodo(
    slug="shots_on", label="Chutes no alvo", coluna="shots_on",
    nomes_mercado=frozenset({"player shots on target", "shots on target",
                             "player shots on goal", "shots on target by player"}),
    min_atuacoes=5,
    rotulo_linha="{n} ou mais chutes no alvo",
)

SHOTS = Metodo(
    slug="shots", label="Chutes", coluna="shots_total",
    nomes_mercado=frozenset({"player shots", "total shots by player",
                             "player total shots", "shots"}),
    min_atuacoes=5,
    rotulo_linha="{n} ou mais chutes",
)

FOULS = Metodo(
    slug="fouls", label="Faltas cometidas", coluna="fouls_committed",
    nomes_mercado=frozenset({"player fouls committed", "fouls committed",
                             "player fouls"}),
    min_atuacoes=6,
    rotulo_linha="{n} ou mais faltas",
)

TACKLES = Metodo(
    slug="tackles", label="Desarmes", coluna="tackles_total",
    nomes_mercado=frozenset({"player tackles", "tackles", "player tackles made"}),
    min_atuacoes=6,
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
    min_atuacoes=6,
    rotulo_linha="{n} ou mais passes",
)

METODOS: tuple = (SAVES, SHOTS_ON, SHOTS, FOULS, TACKLES, PASSES)

POR_SLUG = {m.slug: m for m in METODOS}

#: Todas as colunas que o motor le de player_match_stats, numa lista so' --
#: e' o SELECT do player_history.
COLUNAS = tuple(dict.fromkeys(m.coluna for m in METODOS))


def de(slug: str) -> Metodo | None:
    return POR_SLUG.get(slug)
