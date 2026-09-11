"""O desenho de cada motor: o que entra, por onde passa, o que reprova.

POR QUE ISTO NÃO É UM TEXTO NO FRONTEND
---------------------------------------
A tela poderia ter o fluxo escrito à mão em TSX. Seria a quarta cópia da mesma
coisa neste projeto -- depois do registro de motores, do registro de comandos e
da sequência do "Rodar Tudo", que já divergiram cada uma pelo menos uma vez --
e a cópia que diverge aqui é a pior de todas: um fluxograma errado não quebra
nada, só ensina errado.

Então os NÚMEROS saem do config real do motor, lidos em tempo de execução
(`_limiar`). Baixar um limiar em `pick_engine/config.py` muda o desenho na tela
sozinho. Se o motor não estiver no path, o campo vem `None` e a tela mostra o
degrau sem número em vez de mostrar um número velho.

O que É escrito aqui é a ORDEM e o PAPEL de cada camada -- isso não existe como
dado em lugar nenhum do código, existe como desenho. A fonte escrita dele são as
skills de auditoria (`.claude/skills/auditar-motor-*`), e é com elas que este
arquivo tem que concordar.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: IMPORT PREGUICOSO, e nao no topo (2026-09-11).
#:
#: `settlement_bridge` monta o motor no caminho e inicializa o pool de conexao
#: no momento do import. No topo deste modulo, isso acontecia durante a COLETA
#: do pytest -- antes de qualquer fixture -- e o teste do pool passava a receber
#: uma conexao REAL de producao no lugar do dube dele. A trava do conftest nao
#: pega esse caminho: ela substitui `database.get_connection`, e o pool monta a
#: conexao direta por dentro.
#:
#: Aqui o import so' acontece quando alguem pede o fluxo, que e' dentro de uma
#: rota. `None` continua significando "motor fora do caminho".
def _registro():
    try:
        from settlement_bridge import engine_registry
        return engine_registry
    except Exception as e:  # pragma: no cover - ambiente sem o motor
        logger.debug("[FLUXO] registro do motor indisponivel: %s", str(e)[:120])
        return None


#: Mantido pra o teste poder anular o registro com monkeypatch sem mexer no
#: `settlement_bridge` inteiro.
engine_registry = None


def _config_pre_live():
    try:
        from services.pick_engine.config import DEFAULT_CONFIG
        return DEFAULT_CONFIG
    except Exception as e:
        logger.debug("[FLUXO] config do pre-live indisponivel: %s", str(e)[:120])
        return None


def _config_live():
    try:
        from services.pick_engine_live.config import DEFAULT_LIVE_CONFIG
        return DEFAULT_LIVE_CONFIG
    except Exception as e:
        logger.debug("[FLUXO] config do ao vivo indisponivel: %s", str(e)[:120])
        return None


def _limiar(config, campo: str):
    """O valor REAL do config, ou None quando o motor não está alcançável.

    None vira "sem número" na tela. Chutar um padrão aqui seria exibir um
    limiar que talvez não seja o que está rodando -- e o ponto desta tela é
    justamente dizer o que está rodando.
    """
    if config is None:
        return None
    valor = getattr(config, campo, None)
    if isinstance(valor, tuple):
        return list(valor)
    return valor


def _pre_live() -> dict:
    c = _config_pre_live()
    return {
        "slug": "PRE_LIVE",
        "label": "Pré Live",
        "resumo": ("Decide antes da bola rolar, com o histórico dos dois times. "
                   "É o motor de cinco produtos, e todos passam pelas mesmas camadas."),
        "entradas": [
            {"fonte": "match_statistics",
             "o_que": "A folha de cada partida encerrada: gols, escanteios, cartões, "
                      "faltas, chutes, defesas, impedimentos e posse.",
             "origem": "API-Football, coletada pelo Atualizar Jogos"},
            {"fonte": "team_statistics",
             "o_que": "A média de cada time na temporada, já recortada por mando.",
             "origem": "derivada de match_statistics"},
            {"fonte": "odds_values",
             "o_que": "As linhas e os preços de cada casa, por mercado.",
             "origem": "API-Football, coletada pelo Capturar Odds"},
            {"fonte": "referee_stats",
             "o_que": "A média de cartões do árbitro da partida.",
             "origem": "derivada de match_statistics"},
            {"fonte": "league_standings",
             "o_que": "A tabela da liga, para saber o peso do adversário e a "
                      "necessidade de cada lado.",
             "origem": "API-Football"},
            {"fonte": "competition_rules",
             "o_que": "O regulamento do mata-mata: ida e volta, gol fora, prorrogação.",
             "origem": "IA, uma vez por competição e temporada"},
        ],
        "camadas": [
            {"nome": "Elegibilidade da partida",
             "faz": "Só jogo de HOJE, de liga cadastrada e ativa, com os dois times "
                    "tendo histórico suficiente no banco.",
             "reprova": "Jogo de amanhã, liga não acompanhada, time sem amostra.",
             "limiares": {"mínimo de jogos no histórico": _limiar(c, "min_amostra")}},
            {"nome": "Pool do mercado",
             "faz": "Junta os jogos que descrevem aquele mercado para aqueles dois "
                    "times, recortando por mando quando o mercado é de um lado só.",
             "reprova": "Amostra que não sustenta a taxa.",
             "limiares": {"amostra considerada rica": _limiar(c, "sample_rich_n")}},
            {"nome": "Taxa histórica",
             "faz": "Quantas vezes aquilo aconteceu no pool, com peso maior para "
                    "jogo recente e para adversário de mais força.",
             "reprova": "Taxa abaixo do piso.",
             "limiares": {"taxa mínima": _limiar(c, "min_taxa"),
                          "janelas de recência (dias, peso)": _limiar(c, "temporal_tiers")}},
            {"nome": "Modelo probabilístico",
             "faz": "Binomial Negativa para contagens superdispersas (escanteios, "
                    "faltas) e Poisson para gols, contra a linha ofertada.",
             "reprova": "Modelo discordando demais da taxa bruta.",
             "limiares": {"desacordo máximo entre modelo e taxa":
                          _limiar(c, "model_disagreement_threshold")}},
            {"nome": "Contexto da partida",
             "faz": "Mata-mata, agregado, clássico, time já classificado, desfalque. "
                    "Barra o pick que o contexto contradiz.",
             "reprova": "Contexto que desmente a estatística.",
             "limiares": {}},
            {"nome": "Confiança",
             "faz": "Combina consistência (C), qualidade do dado (Q) e tamanho da "
                    "amostra (K) num número só.",
             "reprova": "Confiança abaixo do piso.",
             "limiares": {"confiança mínima": _limiar(c, "min_confidence"),
                          "peso consistência": _limiar(c, "weight_c"),
                          "peso qualidade": _limiar(c, "weight_q"),
                          "peso amostra": _limiar(c, "weight_k")}},
            {"nome": "Preço",
             "faz": "Compara a probabilidade com o preço da casa. O preço ELIMINA "
                    "aqui, e não ordena: a escolha do pick é estatística.",
             "reprova": "Odd fora da faixa, edge ou EV insuficiente, poucas casas cotando.",
             "limiares": {"odd mínima": _limiar(c, "min_odd"),
                          "odd máxima": _limiar(c, "max_odd"),
                          "edge mínimo": _limiar(c, "min_edge"),
                          "EV mínimo": _limiar(c, "min_ev"),
                          "casas cotando no mínimo": _limiar(c, "min_bookmakers_count")}},
            {"nome": "Gate de IA",
             "faz": "Um revisor independente lê o pick pronto, com o contexto da "
                    "partida e o perfil da liga.",
             "reprova": "Só VETA, e nunca define o pick. Falha aberto: indisponível "
                        "não é aprovação implícita, é pick mantido.",
             "limiares": {}},
            {"nome": "Escolha e stake",
             "faz": "Entre os aprovados, ordena por consistência estatística e "
                    "dimensiona a entrada pelo plano de stake.",
             "reprova": "—",
             "limiares": {}},
        ],
    }


def _live() -> dict:
    c = _config_live()
    return {
        "slug": "LIVE",
        "label": "Ao Vivo",
        "resumo": ("Decide com a partida rolando, sobre o tempo que FALTA. A janela "
                   "é o minuto: dado de quatro minutos atrás já descreve outro jogo."),
        "entradas": [
            {"fonte": "/fixtures?live=all",
             "o_que": "Todas as partidas ao vivo do mundo, numa chamada só.",
             "origem": "API-Football, uma requisição por rodada"},
            {"fonte": "/fixtures/statistics",
             "o_que": "A folha acumulada da partida em andamento.",
             "origem": "API-Football, só das partidas elegíveis"},
            {"fonte": "/fixtures/events",
             "o_que": "Gol, cartão, substituição e expulsão COM o minuto de cada um. "
                      "É a única fonte de quando.",
             "origem": "API-Football"},
            {"fonte": "/odds/live",
             "o_que": "O preço ao vivo, buscado só de quem passou na triagem.",
             "origem": "API-Football"},
            {"fonte": "live_match_observations",
             "o_que": "Uma linha por passada nossa, mesmo sem pick. É o que constrói "
                      "janela e tendência, porque a folha só sabe somar.",
             "origem": "gravada pelo próprio motor"},
        ],
        "camadas": [
            {"nome": "Orçamento de API",
             "faz": "Teto rígido de requisições por rodada. Atingiu, a rodada para.",
             "reprova": "—",
             "limiares": {"teto de requisições": _limiar(c, "max_requisicoes"),
                          "partidas por rodada": _limiar(c, "max_partidas")}},
            {"nome": "Seleção de partidas",
             "faz": "Corta por liga ativa, status em andamento e janela de minuto. "
                    "Ordena por minuto decrescente e corta no teto.",
             "reprova": "Liga não acompanhada, jogo fora da janela, pick recente "
                        "demais na mesma partida.",
             "limiares": {"minuto inicial": _limiar(c, "minuto_inicial"),
                          "minuto final": _limiar(c, "minuto_final")}},
            {"nome": "Frescor do dado",
             "faz": "Compara o minuto que o provedor diz com o minuto esperado pelo "
                    "relógio. Bloqueia a análise inteira antes de qualquer modelo.",
             "reprova": "Dado atrasado não produz pick pior, produz pick sobre outra "
                        "partida.",
             "limiares": {"atraso máximo (minutos)": _limiar(c, "atraso_maximo_minutos")}},
            {"nome": "Estado e ritmo",
             "faz": "Placar, expulsão, pressão e a tendência das últimas janelas de "
                    "10, 15 e 5 minutos.",
             "reprova": "—",
             "limiares": {}},
            {"nome": "Projeção residual",
             "faz": "Taxa por minuto encolhida contra o baseline da liga, e projetada "
                    "sobre os minutos que faltam. O peso do próprio jogo cresce com "
                    "o relógio e sai da dispersão medida da família.",
             "reprova": "—",
             "limiares": {"famílias analisadas": _limiar(c, "familias")}},
            {"nome": "Triagem",
             "faz": "Exige que a projeção se afaste do baseline antes de gastar uma "
                    "requisição com o preço.",
             "reprova": "Partida que roda na média da liga nunca tem a odd consultada.",
             "limiares": {}},
            {"nome": "Avaliação e gates",
             "faz": "Probabilidade da linha, encolhimento contra o mercado, EV, "
                    "convergência de sinais.",
             "reprova": "Linha já batida pelo placar, EV ou confiança baixos, odd "
                        "fora da faixa, sinais contraditórios, linha sem o lado "
                        "contrário cotado.",
             "limiares": {"EV mínimo": _limiar(c, "ev_minimo"),
                          "confiança mínima": _limiar(c, "confianca_minima"),
                          "sinais convergentes mínimos": _limiar(c, "sinais_minimos_convergentes")}},
            {"nome": "Gate de IA e gravação",
             "faz": "Mesmo revisor do Pré Live. O pick carimba a validade da odd, "
                    "porque preço ao vivo evapora.",
             "reprova": "Só VETA.",
             "limiares": {"validade da odd (s)": _limiar(c, "validade_odd_segundos")}},
        ],
    }


def _pick_boost() -> dict:
    return {
        "slug": "PICK_BOOST",
        "label": "Pick Boost",
        "resumo": ("Um mercado só, combinado: Over 1.5 no jogo inteiro com Under 2.5 "
                   "no primeiro tempo. Procura o jogo que cabe nesse desenho."),
        "entradas": [
            {"fonte": "match_statistics",
             "o_que": "Gols do jogo inteiro e do primeiro tempo, separados.",
             "origem": "coletada pelo Atualizar Jogos"},
            {"fonte": "odds_values",
             "o_que": "O preço das duas pernas.",
             "origem": "coletada pelo Capturar Odds"},
        ],
        "camadas": [
            {"nome": "Perna do jogo inteiro",
             "faz": "Taxa histórica de Over 1.5 FT dos dois times.",
             "reprova": "Time que não sustenta o volume de gols.",
             "limiares": {}},
            {"nome": "Perna do primeiro tempo",
             "faz": "Taxa histórica de Under 2.5 HT, que é a perna que costuma "
                    "eliminar.",
             "reprova": "Time de primeiro tempo aberto.",
             "limiares": {}},
            {"nome": "Combinação",
             "faz": "As duas condições valem juntas, então a probabilidade combinada "
                    "é o que decide.",
             "reprova": "Combinação fora do piso.",
             "limiares": {}},
            {"nome": "Liquidação",
             "faz": "Lê o placar do fixture, como os outros motores.",
             "reprova": "—",
             "limiares": {}},
        ],
    }


def _player_stats() -> dict:
    return {
        "slug": "PLAYER_STATS",
        "label": "Pick Jogador",
        "resumo": ("Prop de um jogador só. É o motor de maior variância do projeto, "
                   "e o único cujo pick acompanha uma vaga no time e não a partida."),
        "entradas": [
            {"fonte": "player_match_stats",
             "o_que": "A folha de cada jogador por partida: defesas, chutes, chutes "
                      "no alvo, faltas, desarmes e passes.",
             "origem": "API-Football /fixtures/players, coletada sob demanda"},
            {"fonte": "/fixtures/lineups",
             "o_que": "A escalação oficial, que diz se o titular do pick vai jogar.",
             "origem": "API-Football, varrida perto do jogo"},
            {"fonte": "odds_values",
             "o_que": "O mercado do jogador na casa, que muda de nome por mando.",
             "origem": "coletada pelo Capturar Odds"},
        ],
        "camadas": [
            {"nome": "Catálogo de métodos",
             "faz": "Seis métodos independentes, cada um com a própria dispersão "
                    "medida. Três rodam todo dia, três só sob demanda.",
             "reprova": "—",
             "limiares": {}},
            {"nome": "Histórico do jogador",
             "faz": "As atuações dele como TITULAR, porque o pick é do titular.",
             "reprova": "Jogador sem amostra, ou com fatia de participação que é "
                        "ruído.",
             "limiares": {}},
            {"nome": "Modelo por método",
             "faz": "Binomial Negativa com a dispersão daquele método, contra a "
                    "linha do mercado.",
             "reprova": "Probabilidade abaixo do piso.",
             "limiares": {}},
            {"nome": "Escalação",
             "faz": "A varredura da escalação oficial confere se o titular começou.",
             "reprova": "Fora do XI anula o pick; o substituto soma na vaga.",
             "limiares": {}},
            {"nome": "Gate de IA",
             "faz": "Revisor independente, no modelo mais caro, porque é aposta de "
                    "alta variância.",
             "reprova": "Só VETA.",
             "limiares": {}},
        ],
    }


_DESENHOS = {
    "PRE_LIVE": _pre_live,
    "LIVE": _live,
    "PICK_BOOST": _pick_boost,
    "PLAYER_STATS": _player_stats,
}


def fluxo_dos_motores() -> dict:
    """O desenho de cada motor, com os métodos que o registro do motor declara.

    Os métodos NÃO são escritos aqui: saem de `engine_registry`, que é a fonte
    única da arquitetura. Método novo no motor aparece nesta tela sozinho.
    """
    motores = []
    registro = {}
    catalogo = engine_registry if engine_registry is not None else _registro()
    if catalogo is not None:
        try:
            registro = {m.slug: m for m in catalogo.MOTORES}
        except Exception as e:
            logger.warning("[FLUXO] registro do motor ilegivel: %s", str(e)[:160])

    for slug, desenho in _DESENHOS.items():
        bloco = desenho()
        do_registro = registro.get(slug)
        if do_registro is not None:
            bloco["label"] = do_registro.label
            bloco["metodos"] = [
                {"slug": met.slug, "label": met.label, "versao": met.versao,
                 "tabela": met.tabela_picks}
                for met in do_registro.metodos
            ]
        else:
            bloco["metodos"] = []
        motores.append(bloco)

    return {
        "motores": motores,
        # Falso quando o motor não está no path: a tela mostra o desenho, mas
        # sem os métodos e sem os limiares, e precisa poder dizer isso.
        "derivado": bool(registro),
        "limiares_disponiveis": _config_pre_live() is not None,
    }
