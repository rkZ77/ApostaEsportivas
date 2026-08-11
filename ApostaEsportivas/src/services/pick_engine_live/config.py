"""Configuracao do Motor Live -- toda ela por variavel de ambiente.

POR QUE POR ENV E NAO POR DATACLASS FIXA COMO O PRE-JOGO
--------------------------------------------------------
`pick_engine/config.py` e' um dataclass congelado porque os limites do
pre-jogo sao decisao de produto ja' assentada. Aqui e' o oposto: a V1 existe
pra ser calibrada rodando contra jogo real, e o parametro que mais importa
(quanta requisicao de API a rodada pode gastar) precisa poder mudar sem
deploy. Mexer num numero nao pode custar um commit.

O DEFAULT DE TUDO E' O LADO SEGURO
----------------------------------
`LIVE_ENGINE_ENABLED` nasce FALSE e `LIVE_ENGINE_DRY_RUN` nasce TRUE. Ou seja:
um deploy que esqueca de configurar qualquer coisa nao gera pick, nao grava
nada e nao gasta cota. O oposto do default do pre-jogo (`SIDE_EFFECTS=on`),
e de proposito -- la' esquecer a variavel nao pode DESLIGAR producao; aqui
esquecer a variavel nao pode LIGAR um consumo de API que ninguem pediu.

TRAVA DE AMBIENTE
-----------------
`exigir_ambiente_dev()` recusa rodar fora de `DB_ENV=dev`. Nao e' zelo
abstrato: `.env` na raiz tem DB_HOST_PROD, e `get_connection()` cai nele
quando DB_ENV nao existe -- foi assim que teste ja escreveu em producao
(ver website/backend/tests/conftest.py). Um motor novo, ainda sem historico
medido, nao pode ter esse caminho aberto.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _flag(nome: str, padrao: bool) -> bool:
    bruto = os.getenv(nome)
    if bruto is None:
        return padrao
    return bruto.strip().lower() in ("1", "true", "on", "yes", "sim")


def _inteiro(nome: str, padrao: int) -> int:
    try:
        return int(os.getenv(nome, str(padrao)))
    except (TypeError, ValueError):
        return padrao


def _decimal(nome: str, padrao: float) -> float:
    try:
        return float(os.getenv(nome, str(padrao)))
    except (TypeError, ValueError):
        return padrao


class AmbienteInvalido(RuntimeError):
    """Tentativa de rodar o Motor Live fora do ambiente permitido."""


@dataclass(frozen=True)
class LiveEngineConfig:
    # ── Interruptores ────────────────────────────────────────────────────
    habilitado: bool = False
    modo: str = "dev"
    #: Em dry run o motor calcula tudo, loga a decisao e NAO grava em
    #: picks_live. E' o modo de validar o modelo sem sujar o historico com
    #: pick que so' existiu pra teste.
    dry_run: bool = True
    #: Revisao por IA. FALSE na V1 por decisao explicita: a IA custa token por
    #: partida por ciclo, e antes de gastar isso o motor estatistico precisa
    #: provar que decide bem sozinho.
    ai_review: bool = False

    # ── Teto de consumo ──────────────────────────────────────────────────
    #: Jogos analisados por rodada. E' o teto que mais controla custo: cada
    #: jogo custa 1 chamada de estatistica e, se houver oportunidade, mais 1
    #: de odd.
    max_partidas: int = 3
    #: Teto RIGIDO de requisicoes por execucao. Atingiu, a rodada para -- nao
    #: "avisa e continua". Ver live_feed.OrcamentoEsgotado.
    max_requisicoes: int = 15

    # ── Janela de analise ────────────────────────────────────────────────
    #: Antes disso a amostra do proprio jogo e' curta demais pra corrigir o
    #: baseline; depois disso sobra pouco tempo pro evento acontecer e a odd
    #: fica cara demais pro risco.
    minuto_inicial: int = 15
    minuto_final: int = 80

    # ── Gates de aprovacao ───────────────────────────────────────────────
    ev_minimo: float = 0.05
    confianca_minima: float = 0.58
    odd_minima: float = 1.40
    odd_maxima: float = 4.00
    #: Amostra minima do proprio jogo pra familia analisada. Escanteio: um
    #: jogo com 0 escanteios aos 20 minutos nao sustenta estimativa nenhuma.
    minutos_minimos_observados: int = 15

    # ── Anti-inundacao ───────────────────────────────────────────────────
    #: Quantos picks a mesma partida pode gerar na vida inteira dela.
    max_picks_por_partida: int = 2
    #: Intervalo minimo, em minutos de JOGO, entre dois picks da mesma
    #: partida. Sem isso uma partida movimentada vira o produto do dia.
    minutos_entre_picks: int = 20

    # ── Validade da odd ──────────────────────────────────────────────────
    #: Segundos que a odd publicada vale. Odd ao vivo evapora: sem carimbo de
    #: validade o usuario registra uma aposta que nao existe mais e o ROI
    #: publicado deixa de ser alcancavel.
    validade_odd_segundos: int = 180

    # ── Mercados da V1 ───────────────────────────────────────────────────
    #: Escanteios e gols. Cartoes, chutes e o resto entram depois, quando o
    #: modelo residual estiver medido nestes dois.
    familias: tuple = ("corners", "goals")

    # ── Ligas ────────────────────────────────────────────────────────────
    #: Vazio = qualquer liga cadastrada em `leagues`. Preencher restringe
    #: ainda mais (util pra um teste dirigido).
    ligas_permitidas: tuple = field(default_factory=tuple)

    # ── Eventos ──────────────────────────────────────────────────────────
    #: Buscar /fixtures/events (gol, cartao, penalti, substituicao com o
    #: minuto de cada um). Custa 1 requisicao por partida. Vale a pena porque
    #: e' a UNICA fonte de "quando" -- a folha de estatistica so' devolve
    #: acumulado, entao sem isso o motor sabe que houve um vermelho mas nao
    #: sabe se foi aos 12' ou aos 80', que sao jogos completamente diferentes.
    buscar_eventos: bool = True

    # ── Freshness ────────────────────────────────────────────────────────
    #: Acima deste atraso (em minutos de jogo desde a ultima leitura util) o
    #: dado e' classificado DELAYED; acima do dobro, STALE. Pick nunca sai com
    #: dado STALE: ao vivo, decidir sobre um estado que ja mudou nao produz um
    #: pick ruim, produz um pick sobre outra partida.
    atraso_maximo_minutos: int = 4

    # ── Pesos do Pressure Score ──────────────────────────────────────────
    #: NAO sao numeros medidos -- sao um ponto de partida declarado, pra
    #: poderem ser calibrados contra resultado depois. Ficam aqui, e nao
    #: cravados no modelo, exatamente por isso.
    #: A ordem reflete o quanto cada sinal costuma antecipar volume ofensivo:
    #: finalizacao no alvo e' o mais direto, posse e' o mais enganoso.
    peso_shots_on_target: float = 0.26
    peso_shots: float = 0.16
    #: "Dangerous Attacks" NAO faz parte da resposta padrao de
    #: /fixtures/statistics da API-Football (os tipos publicados sao Shots on
    #: Goal, Shots off Goal, Total Shots, Blocked Shots, Shots insidebox,
    #: Shots outsidebox, Fouls, Corner Kicks, Offsides, Ball Possession,
    #: Yellow/Red Cards, Goalkeeper Saves, passes e expected_goals). O peso
    #: fica aqui porque algumas ligas/planos publicam o campo, e quando ele
    #: existe e' um dos melhores sinais de volume ofensivo. Quando nao existe,
    #: o componente sai da conta e os outros sao renormalizados -- nunca entra
    #: como zero.
    peso_ataques_perigosos: float = 0.16
    peso_escanteios: float = 0.12
    peso_posse: float = 0.08
    #: Chute bloqueado e chute de dentro da area sao os dois sinais que mais
    #: antecedem ESCANTEIO especificamente (bloqueio vira escanteio com
    #: frequencia alta). Entram na pressao geral com peso pequeno e sao usados
    #: com peso proprio no modelo de escanteios.
    peso_bloqueados: float = 0.10
    #: expected_goals vem na folha da API-Football em boa parte das ligas. E' a
    #: medida mais direta de QUALIDADE de chance que existe no feed, e por isso
    #: pesa mais que chute bruto quando esta disponivel.
    peso_xg: float = 0.12

    # ── Ritmo ────────────────────────────────────────────────────────────
    #: Janelas recentes, em minutos, na ordem de preferencia. A primeira que
    #: tiver observacao suficiente e' a usada; as outras entram no rastro.
    janelas_minutos: tuple = (10, 15, 5)
    #: Variacao minima entre a janela recente e a anterior pra chamar de
    #: aceleracao ou desaceleracao. Abaixo disso e' ruido, e o rotulo fica
    #: ESTAVEL.
    limiar_tendencia: float = 0.25

    # ── Convergencia ─────────────────────────────────────────────────────
    #: Quantos sinais precisam apontar na mesma direcao pra o pick ser
    #: considerado sustentado por convergencia. Abaixo disso o LIVE_SIGNAL
    #: cai e a confianca cai junto.
    sinais_minimos_convergentes: int = 3

    @classmethod
    def do_ambiente(cls) -> "LiveEngineConfig":
        ligas_bruto = (os.getenv("LIVE_LEAGUES") or "").strip()
        ligas = tuple(
            int(p) for p in ligas_bruto.replace(";", ",").split(",")
            if p.strip().isdigit()
        )
        return cls(
            habilitado=_flag("LIVE_ENGINE_ENABLED", False),
            modo=(os.getenv("LIVE_ENGINE_MODE") or "dev").strip().lower(),
            dry_run=_flag("LIVE_ENGINE_DRY_RUN", True),
            ai_review=_flag("LIVE_AI_REVIEW", False),
            max_partidas=_inteiro("LIVE_MAX_MATCHES", 3),
            max_requisicoes=_inteiro("LIVE_MAX_API_REQUESTS_PER_RUN", 15),
            minuto_inicial=_inteiro("LIVE_MINUTE_START", 15),
            minuto_final=_inteiro("LIVE_MINUTE_END", 80),
            ev_minimo=_decimal("LIVE_MIN_EV", 0.05),
            confianca_minima=_decimal("LIVE_MIN_CONFIDENCE", 0.58),
            odd_minima=_decimal("LIVE_MIN_ODD", 1.40),
            odd_maxima=_decimal("LIVE_MAX_ODD", 4.00),
            max_picks_por_partida=_inteiro("LIVE_MAX_PICKS_PER_FIXTURE", 2),
            minutos_entre_picks=_inteiro("LIVE_MINUTES_BETWEEN_PICKS", 20),
            validade_odd_segundos=_inteiro("LIVE_ODD_VALIDITY_SECONDS", 180),
            ligas_permitidas=ligas,
            buscar_eventos=_flag("LIVE_FETCH_EVENTS", True),
            atraso_maximo_minutos=_inteiro("LIVE_MAX_DATA_AGE_MINUTES", 4),
            limiar_tendencia=_decimal("LIVE_TREND_THRESHOLD", 0.25),
            sinais_minimos_convergentes=_inteiro("LIVE_MIN_CONVERGENT_SIGNALS", 3),
        )

    def resumo(self) -> str:
        return (
            f"modo={self.modo} dry_run={self.dry_run} ai_review={self.ai_review} "
            f"max_partidas={self.max_partidas} max_requisicoes={self.max_requisicoes} "
            f"janela={self.minuto_inicial}'-{self.minuto_final}' "
            f"ev_min={self.ev_minimo:+.0%} conf_min={self.confianca_minima:.0%} "
            f"odd=[{self.odd_minima}, {self.odd_maxima}]"
        )


#: Config padrao, pra modulos puros (pressao, ritmo, sinal) poderem ser
#: chamados sem o chamador montar uma config so' pra isso. A config real vem
#: sempre do ambiente no pipeline.
DEFAULT_LIVE_CONFIG = LiveEngineConfig()

#: Versao do motor gravada em cada pick. Muda quando a matematica muda -- e'
#: o que permite, depois, separar "pick ruim" de "pick de outra versao".
ENGINE_VERSION = "live_v1.0.0"


def exigir_ambiente_dev() -> None:
    """Recusa rodar fora de DEV. Ver a docstring do modulo.

    `LIVE_ENGINE_ALLOW_PROD=true` e' a valvula de escape consciente, pra o dia
    em que a promocao pra producao for uma decisao tomada -- nao um acidente
    de variavel esquecida.
    """
    if _flag("LIVE_ENGINE_ALLOW_PROD", False):
        return
    db_env = (os.getenv("DB_ENV") or "").strip().lower()
    if db_env != "dev":
        raise AmbienteInvalido(
            f"Motor Live so' roda com DB_ENV=dev (atual: {db_env or 'vazio'}). "
            "Sem isso a conexao cai no banco de PRODUCAO pelo .env da raiz. "
            "Para forcar conscientemente: LIVE_ENGINE_ALLOW_PROD=true."
        )
