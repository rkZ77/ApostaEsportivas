"""Catalogo dos motores e dos metodos de cada um -- fonte unica da
arquitetura nova (2026-08-27).

POR QUE UM REGISTRO, E NAO STRINGS SOLTAS
-----------------------------------------
Ate' aqui "motor" e "pipeline" eram a mesma coisa: cada arquivo de
engine_pipelines/ escrevia o proprio nome ("VIP_ENGINE", "FALTAS_ENGINE") na
coluna `pipeline` de engine_decisions, e o painel do site repetia essa lista
a mao. Sete pipelines viraram sete motores por acidente de arquivo.

A arquitetura passa a ter QUATRO motores, cada um com METODOS:

    PRE_LIVE      vip, dica, multipla, alavancagem, faltas
    LIVE          live
    PICK_BOOST    over15_under25ht
    PLAYER_STATS  saves, shots, shots_on, fouls, tackles, passes

Duas mudancas de taxonomia que o usuario pediu explicitamente e que ESTE
arquivo implementa sozinho, sem tocar em calculo nenhum:

  · FALTAS deixa de ser motor e vira metodo do Pre Live. O fouls_model e o
    faltas_pipeline continuam byte a byte como estao -- o que muda e' onde a
    auditoria o classifica. Mexer no calculo era o unico jeito de "juntar" de
    verdade, e o Pre Live esta' proibido de mudar;
  · DEFESA DE GOLEIRO deixa de ser motor e vira o metodo `saves` do Player
    Stats, que e' o lugar natural dele: sempre foi prop de JOGADOR
    (player_id, line "N ou mais defesas"), nunca um over/under de time.

VERSAO
------
`versao` e' por METODO, nao por motor: o Pre Live tem cinco metodos que mudam
em ritmos diferentes, e "qual versao gerou este pick" precisa responder pelo
metodo que gerou, nao pelo arquivo mais recente do motor.

O numero comeca em 1.0.0 para todo mundo em 27/08/2026. Isso NAO quer dizer
que os metodos sao novos -- o Pre Live roda desde 18/07 -- quer dizer que o
rastreamento de versao comeca aqui. Datar o inicio e' honesto; inventar
"3.4.0" pro vip pra parecer maduro seria numero sem historico atras.

Bumpar a mao ao mexer no calculo do metodo. Nao existe automacao: hash de
arquivo mudaria a versao ao corrigir um comentario.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Metodo:
    slug: str            # identificador estavel, vai pro banco
    label: str           # como aparece no painel
    versao: str          # semver do CALCULO deste metodo
    tabela_picks: str    # onde o pick dele e' gravado ("" = nao grava pick)
    pipeline: str        # nome legado gravado em engine_decisions.pipeline


@dataclass(frozen=True)
class Motor:
    slug: str
    label: str
    prefixo: str         # duas letras do run_id: "PB-20260827-001"
    metodos: tuple


#: Pre Live -- CONGELADO. Nenhuma linha de calculo destes cinco metodos pode
#: mudar (instrucao explicita do usuario). Eles entram aqui so' pra serem
#: auditados sob o mesmo run_id/versao dos motores novos.
PRE_LIVE = Motor(
    slug="PRE_LIVE", label="Pré Live", prefixo="PL",
    metodos=(
        Metodo("vip",         "VIP",         "1.0.0", "picks_vip",         "VIP_ENGINE"),
        Metodo("dica",        "Free",        "1.0.0", "picks_free",        "DICA_ENGINE"),
        Metodo("multipla",    "Múltipla",    "1.0.0", "picks_multiplas",   "MULTIPLA_ENGINE"),
        Metodo("alavancagem", "Alavancagem", "1.0.0", "picks_alavancagem", "ALAVANCAGEM_ENGINE"),
        # Faltas: mercado do Pre Live desde 27/08. Pipeline proprio por razao
        # tecnica (fouls_model nao e' parametrico, ver a docstring dele), nao
        # por ser outro motor.
        Metodo("faltas",      "Faltas",      "1.0.0", "picks_faltas",      "FALTAS_ENGINE"),
    ),
)

#: O Live e' o unico motor que JA' TINHA versao propria antes deste registro:
#: `pick_engine_live.config.ENGINE_VERSION`, gravada em cada pick desde que ele
#: nasceu. A versao aqui e' derivada dela, e nao um numero paralelo -- dois
#: versionamentos da mesma coisa divergem no primeiro bump que alguem esquecer.
def _versao_do_live() -> str:
    try:
        from services.pick_engine_live.config import ENGINE_VERSION
        # "live_v1.0.0" -> "1.0.0": o prefixo ja' esta' dito pelo motor.
        return ENGINE_VERSION.split("_v")[-1]
    except Exception:
        return "1.0.0"


LIVE = Motor(
    slug="LIVE", label="Live", prefixo="LV",
    metodos=(
        Metodo("live", "Ao vivo", _versao_do_live(), "picks_live", "LIVE_ENGINE"),
    ),
)

#: Pick Boost -- os dois mercados sao FIXOS por definicao do metodo. O motor
#: escolhe JOGO, nunca mercado; por isso ha um metodo so'.
PICK_BOOST = Motor(
    slug="PICK_BOOST", label="Pick Boost", prefixo="PB",
    metodos=(
        Metodo("over15_under25ht", "Over 1.5 FT + Under 2.5 HT", "1.0.0",
               "picks_boost", "PICK_BOOST_ENGINE"),
    ),
)

#: Player Stats -- um metodo por estatistica individual. `saves` e' o antigo
#: motor de goleiros, migrado sem alterar goalkeeper_model.
PLAYER_STATS = Motor(
    slug="PLAYER_STATS", label="Player Stats", prefixo="PS",
    metodos=(
        Metodo("saves",    "Defesas de goleiro", "1.0.0", "picks_player_stats", "PLAYER_STATS_ENGINE"),
        Metodo("shots_on", "Chutes no alvo",     "1.0.0", "picks_player_stats", "PLAYER_STATS_ENGINE"),
        Metodo("shots",    "Chutes",             "1.0.0", "picks_player_stats", "PLAYER_STATS_ENGINE"),
        Metodo("fouls",    "Faltas cometidas",   "1.0.0", "picks_player_stats", "PLAYER_STATS_ENGINE"),
        Metodo("tackles",  "Desarmes",           "1.0.0", "picks_player_stats", "PLAYER_STATS_ENGINE"),
        Metodo("passes",   "Passes",             "1.0.0", "picks_player_stats", "PLAYER_STATS_ENGINE"),
    ),
)

MOTORES: tuple = (PRE_LIVE, LIVE, PICK_BOOST, PLAYER_STATS)

MOTOR_POR_SLUG = {m.slug: m for m in MOTORES}

#: (motor_slug, metodo_slug) -> Metodo
_METODOS = {(m.slug, met.slug): met for m in MOTORES for met in m.metodos}

#: pipeline legado -> (Motor, Metodo). E' o que permite `decision_log` seguir
#: gravando "VIP_ENGINE" na coluna antiga e ainda assim classificar a linha no
#: motor certo, sem reescrever nenhum pipeline.
_POR_PIPELINE = {met.pipeline: (m, met)
                 for m in MOTORES for met in m.metodos
                 # PLAYER_STATS compartilha um pipeline legado entre metodos;
                 # a resolucao por pipeline devolve o primeiro, e quem precisa
                 # do metodo exato passa motor+metodo explicito.
                 if met.pipeline not in ("PLAYER_STATS_ENGINE",)}
_POR_PIPELINE["PLAYER_STATS_ENGINE"] = (PLAYER_STATS, PLAYER_STATS.metodos[0])
#: Nome antigo do motor de goleiros. Continua resolvendo pra o metodo `saves`
#: do Player Stats, senao as linhas historicas de engine_decisions ficariam
#: sem motor no painel.
_POR_PIPELINE["GOLEIROS_ENGINE"] = (PLAYER_STATS, PLAYER_STATS.metodos[0])


def metodo(motor_slug: str, metodo_slug: str) -> Metodo | None:
    return _METODOS.get((motor_slug, metodo_slug))


def resolver_pipeline(pipeline: str) -> tuple:
    """(motor_slug, metodo_slug, versao) a partir do nome legado.

    Pipeline desconhecido nao levanta: devolve o proprio nome como motor. Um
    pipeline novo que ainda nao esteja no registro tem que APARECER no painel,
    nao sumir dele -- foi a mesma decisao tomada em routers/admin.py quando o
    painel encontrou um pipeline que a lista dele nao conhecia.
    """
    achado = _POR_PIPELINE.get(pipeline)
    if not achado:
        return (pipeline, None, None)
    m, met = achado
    return (m.slug, met.slug, met.versao)
