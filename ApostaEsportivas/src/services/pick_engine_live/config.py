"""Configuracao do Motor Live -- toda ela por variavel de ambiente.

POR QUE POR ENV E NAO POR DATACLASS FIXA COMO O PRE-JOGO
--------------------------------------------------------
`pick_engine/config.py` e' um dataclass congelado porque os limites do
pre-jogo sao decisao de produto ja' assentada. Aqui e' o oposto: a V1 existe
pra ser calibrada rodando contra jogo real, e o parametro que mais importa
(quanta requisicao de API a rodada pode gastar) precisa poder mudar sem
deploy. Mexer num numero nao pode custar um commit.

O DEFAULT INVERTEU EM 2026-08-28 · O MOTOR VIROU PRODUTO
--------------------------------------------------------
`LIVE_ENGINE_ENABLED` nascia FALSE e `LIVE_ENGINE_DRY_RUN` nascia TRUE: um
deploy que esquecesse de configurar nao gerava pick, nao gravava nada e nao
gastava cota. Era o default certo enquanto o Live era um motor em validacao --
esquecer a variavel nao podia LIGAR um consumo de API que ninguem pediu.

Agora o Live e' produto publicado: a aba esta' aberta pro assinante e o feed
responde pra todo VIP. Com o default antigo, o assinante abria "Picks Ao Vivo"
e via "o motor nao esta' rodando" pra sempre -- e ninguem percebia, porque
ninguem reclama de uma aba que so' diz que nao tem nada.

Entao os defaults viraram o comportamento certo, como no pre-jogo
(`SIDE_EFFECTS=on`): LIGADO e GRAVANDO. As variaveis continuam sendo lidas --
quem quiser um ambiente sem Live seta `LIVE_ENGINE_ENABLED=false` --, mas
nenhuma precisa existir pro produto funcionar.

TRAVA DE AMBIENTE (REMOVIDA EM 2026-08-28)
------------------------------------------
O texto abaixo descreve a trava como ela era. Ela foi retirada junto com a
publicacao do produto: um motor que so' escreve em DEV nao pode alimentar uma
aba que o assinante abre em producao.

O QUE PROTEGE AGORA, no lugar dela: o motor so' roda por acao explicita -- o
botao do /admin ou o comando do CLI --, nunca sozinho. Nao ha' agendador neste
projeto desde 01/08. E ele grava no banco pra onde o processo que o disparou ja'
aponta, que e' a mesma regra dos outros seis motores.

O texto historico, pra quem for reabrir a decisao:

`exigir_ambiente_dev()` recusava rodar fora de `DB_ENV=dev`. Nao era zelo
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
    #: Revisao por IA. TRUE desde 2026-09-04, por decisao do usuario.
    #:
    #: Era FALSE na V1 com este argumento: "a IA custa token por partida por
    #: ciclo, e antes de gastar isso o motor estatistico precisa provar que
    #: decide bem sozinho". O custo que ele descrevia nao existe mais do jeito
    #: que existia -- a chamada nao e' por partida analisada, e' por pick
    #: GRAVADO (ver o gate em live_pipeline, depois da duplicata e do dry run),
    #: entao uma rodada que nao gera pick nenhum nao gasta nada.
    #:
    #: A flag continua servindo pra desligar (LIVE_AI_REVIEW=false).
    ai_review: bool = True

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
    #: PISO DE CONFIANCA. Esta' ACOPLADO a uma formula que subestima o
    #: desacordo com o mercado, e mexer num sem o outro quebra o motor.
    #:
    #: Medido em 2026-09-05: o termo A de `signal_score.live_confidence` compara
    #: a probabilidade DEPOIS do encolhimento com a do mercado, e o
    #: encolhimento e' justamente uma aproximacao do mercado -- entao o que
    #: sobra e' o desacordo real vezes `w = minuto/(minuto+45)`. Nos 7 picks de
    #: DEV, tres deles discordavam do mercado em ~30 pontos e receberam de 0.39
    #: a 0.55 no termo que existe pra punir isso.
    #:
    #: Trocar A pela divergencia real, sozinho, derruba 6 dos 7 abaixo deste
    #: 0.58 -- o que nao e' uma correcao, e' desligar o motor sem dizer. Por
    #: isso a divergencia real hoje e' MEDIDA e gravada
    #: (`confidence_breakdown.divergencia_modelo` e `A_com_divergencia_real` no
    #: engine_debug) e nao pontua. Quando houver amostra, os dois mudam na
    #: mesma mexida: A passa a usar a divergencia real e este piso cai junto.
    confianca_minima: float = 0.58
    #: PISO DE ODD 1.49 desde 2026-08-30 (decisao do usuario). Era 1.40.
    #:
    #: Nao e' calibragem: e' escolha de produto. Abaixo de 1.49 o pick precisa
    #: acertar quase sempre pra pagar a variancia -- e o motor Live ainda tem
    #: historico curto, entao a margem que ele afirma ter e' menos confiavel
    #: que a do pre-jogo. Um piso mais alto compra menos picks e cada um deles
    #: paga mais quando entra.
    odd_minima: float = 1.49
    odd_maxima: float = 4.00
    #: PISO DE PROBABILIDADE (2026-08-20). Nao existia, e a ausencia dele e' o
    #: que deixou passar os dois piores picks dos 7 gravados em DEV:
    #:
    #:     #5  goals Under 1.5  @3.50  probabilidade 31,0%  EV +8,6%   RED
    #:     #6  corners Under 11 @2.62  probabilidade 41,4%  EV +8,4%   -
    #:
    #: Os dois passaram por EV, e o EV veio da ODD, nao da leitura do jogo. O
    #: pre-jogo ja' tinha um piso equivalente (config.min_taxa = 0.60) desde
    #: sempre; o motor ao vivo nasceu sem, e com selecao por maior EV isso
    #: significa que quanto pior a probabilidade, mais alta a odd que a
    #: sustenta, e mais facil o candidato vencer a disputa interna.
    #:
    #: 0.55 e' abaixo do piso do pre-jogo de proposito: a estimativa daqui e'
    #: residual (o tempo que FALTA), entao ela e' legitimamente mais baixa que
    #: uma taxa historica de jogo inteiro. O que ela nao pode ser e' um
    #: cara-ou-coroa publicado como pick.
    probabilidade_minima: float = 0.55
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
    #: Escanteios, gols, cartoes e faltas. Chutes entra depois: tem o baseline
    #: residual medido, falta a decisao de liga-lo.
    #:
    #: Cartoes entrou por ultimo e por dois motivos proprios: e' a unica
    #: familia cujo numero ainda chega ao vivo quando a folha de estatistica
    #: nao vem (o feed de eventos publica cartao), e a unica com uma terceira
    #: estimativa independente do jogo -- a media de quem apita.
    #:
    #: Faltas entrou em 2026-09-04 (pedido do usuario): o feed ja publicava o
    #: contador e o residual foi medido (24.82 por partida em 1.189). O que ela
    #: NAO tem hoje e' oferta -- ver a nota em live_odds.NOMES_POR_FAMILIA.
    familias: tuple = ("corners", "goals", "cards", "fouls")

    #: Jogos apitados na liga pra media do arbitro valer de baseline. Mesmo
    #: numero de cards_referee_min_games no pre-jogo, e o mesmo motivo: abaixo
    #: disso a media e' ruido, e a alternativa nao e' "usar assim mesmo", e'
    #: cair na constante -- que e' o que baseline_do_arbitro faz.
    cards_arbitro_min_jogos: int = 3

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
            # Default LIGADO desde 28/08 · ver o topo do arquivo.
            habilitado=_flag("LIVE_ENGINE_ENABLED", True),
            modo=(os.getenv("LIVE_ENGINE_MODE") or "dev").strip().lower(),
            # Default GRAVANDO desde 28/08 · dry run que nasce ligado num
            # produto publicado significa aba que nunca recebe pick.
            dry_run=_flag("LIVE_ENGINE_DRY_RUN", False),
            ai_review=_flag("LIVE_AI_REVIEW", True),
            max_partidas=_inteiro("LIVE_MAX_MATCHES", 3),
            max_requisicoes=_inteiro("LIVE_MAX_API_REQUESTS_PER_RUN", 15),
            minuto_inicial=_inteiro("LIVE_MINUTE_START", 15),
            minuto_final=_inteiro("LIVE_MINUTE_END", 80),
            ev_minimo=_decimal("LIVE_MIN_EV", 0.05),
            confianca_minima=_decimal("LIVE_MIN_CONFIDENCE", 0.58),
            probabilidade_minima=_decimal("LIVE_MIN_PROBABILITY", 0.55),
            odd_minima=_decimal("LIVE_MIN_ODD", 1.49),
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
            f"prob_min={self.probabilidade_minima:.0%} "
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
    """NAO RECUSA MAIS NADA (2026-08-28) · ver o topo do modulo.

    A funcao fica, e o nome fica, porque ela e' chamada de tres lugares e um
    `pass` aqui e' mais honesto que remover as chamadas: quem for reabrir a
    decisao encontra a explicacao no lugar onde ela era aplicada, e nao um
    vazio.

    O que protege no lugar da trava: o motor so' roda por acao explicita -- o
    botao do /admin ou o comando do CLI --, e grava no banco pra onde o processo
    que o disparou ja' aponta. E' a mesma regra dos outros seis motores.
    """
    return
