"""Perfil de competicao -- fonte unica de verdade por league_id, substituindo
as constantes espalhadas em:
  - ai/ai_suggestions_service.py::NEUTRAL_VENUE_LEAGUES
  - services/match_stats_service.py::NATIONAL_TEAM_LEAGUE_IDS
  - services/national_team_profile_service.py::_classify_competition
  - ai/ai_tipster_orchestrator.py (branch "if league_id == 1")
  - ai/prompts/__init__.py::_LEAGUE_MAP

Os valores abaixo espelham o comportamento ATUAL de cada uma dessas
constantes (nao mudam nada -- so consolidam). Uma inconsistencia pre-existente
fica visivel ao juntar tudo num lugar so: Copa America/Euro/AFCON/Asiatica
(league_id 9/4/14/23) sao "selecao nacional" (is_national_team=True) mas
ficam no grupo de peso "Amistoso/Outra" em vez de "Copa do Mundo" em
_classify_competition() hoje -- mantido como esta de proposito (nao e escopo
desta consolidacao mudar comportamento), mas vale revisar depois.

Deteccao automatica de GROUP_STAGE vs KNOCKOUT_SINGLE vs KNOCKOUT_TWO_LEGS
POR FIXTURE ainda nao e possivel -- a tabela fixtures nao guarda round/stage
(requer o collector novo de round via API-Football, ver plano). Ate la, fases
dentro de um torneio (ex.: Copa do Mundo grupos vs mata-mata) continuam
resolvidas pela tabela de datas ja existente em
ai/prompts/team_prompt_builder.py (_WC2026_PHASES) -- nao duplicada aqui.

CONSOLIDACAO (Prioridade 1 do plano de refatoracao): match_stats_service.
NATIONAL_TEAM_LEAGUE_IDS, ai_suggestions_service.NEUTRAL_VENUE_LEAGUES e
national_team_profile_service._classify_competition() agora DERIVAM daqui
(helpers national_team_league_ids()/neutral_venue_leagues()/
classify_competition_weight_group() abaixo) em vez de manter listas
proprias -- mesmo valor de sempre, uma fonte so. competition_weight_group
usa as strings portuguesas ja consumidas por
national_team_profile_service._calculate_quality_breakdown() ("Copa do
Mundo"/"Eliminatórias"/"Amistoso/Outra") para nao exigir traducao no
chamador."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CompetitionProfile:
    league_id: int
    type: str                        # LEAGUE | INTERNATIONAL_TOURNAMENT | QUALIFIERS | FRIENDLY
    neutral_venue: bool
    is_national_team: bool
    # "Copa do Mundo" | "Eliminatórias" | "Amistoso/Outra" -- strings identicas
    # as chaves ja usadas por national_team_profile_service.WEIGHTS, nao um
    # vocabulario novo pra traduzir na fronteira.
    competition_weight_group: str | None = None


# Eliminatorias de Copa do Mundo + outros qualificatorios (espelha
# match_stats_service.NATIONAL_TEAM_LEAGUE_IDS e
# national_team_profile_service._classify_competition)
# BUG CORRIGIDO 2026-08-01: o 39 estava nesta lista, mas 39 e' a Premier
# League -- esta cadastrada com esse id na propria tabela `leagues` do
# projeto. Ela vinha sendo tratada como eliminatoria de SELECAO: historico
# multi-competicao, perfil de selecao nacional e grupo de peso
# "Eliminatorias". Nao chegou a causar dano porque ainda nao ha nenhum jogo
# de liga 39 em match_statistics; teria mordido no primeiro jogo coletado.
# O id veio herdado de match_stats_service.NATIONAL_TEAM_LEAGUE_IDS, que a
# refatoracao de Prioridade 1 espelhou sem revisar item a item.
_QUALIFIERS_IDS = {31, 32, 33, 34, 35, 36, 37, 38, 882, 780}

_PROFILES: dict[int, CompetitionProfile] = {
    1:  CompetitionProfile(1,  "INTERNATIONAL_TOURNAMENT", neutral_venue=True,  is_national_team=True, competition_weight_group="Copa do Mundo"),
    9:  CompetitionProfile(9,  "INTERNATIONAL_TOURNAMENT", neutral_venue=False, is_national_team=True, competition_weight_group="Amistoso/Outra"),
    4:  CompetitionProfile(4,  "INTERNATIONAL_TOURNAMENT", neutral_venue=False, is_national_team=True, competition_weight_group="Amistoso/Outra"),
    14: CompetitionProfile(14, "INTERNATIONAL_TOURNAMENT", neutral_venue=False, is_national_team=True, competition_weight_group="Amistoso/Outra"),
    23: CompetitionProfile(23, "INTERNATIONAL_TOURNAMENT", neutral_venue=False, is_national_team=True, competition_weight_group="Amistoso/Outra"),
    10: CompetitionProfile(10, "FRIENDLY",                 neutral_venue=False, is_national_team=True, competition_weight_group="Amistoso/Outra"),
    71: CompetitionProfile(71, "LEAGUE", neutral_venue=False, is_national_team=False),
    72: CompetitionProfile(72, "LEAGUE", neutral_venue=False, is_national_team=False),
    # Ligas europeias cobertas (ver tabela `leagues`). Estavam caindo no
    # _DEFAULT, que ja' dava LEAGUE/nao-selecao -- o efeito pratico e' o
    # mesmo, mas explicitas elas param de depender do fallback e o 39 nao
    # volta a ser confundido com eliminatoria.
    39:  CompetitionProfile(39,  "LEAGUE", neutral_venue=False, is_national_team=False),
    78:  CompetitionProfile(78,  "LEAGUE", neutral_venue=False, is_national_team=False),
    140: CompetitionProfile(140, "LEAGUE", neutral_venue=False, is_national_team=False),
    # Copas de clube (2026-08-01). Mata-mata nao acumula jogo suficiente
    # DENTRO da propria competicao pra sustentar analise: a base real mostra
    # 20 jogos/time no Brasileirao contra 1 a 4 em toda competicao de copa,
    # e data_validation.validate_history exige minimo de 5. Por isso elas
    # entram com CLUB_CUP, que faz o historico vir de todas as competicoes
    # (ver uses_all_competitions_history).
    #
    # competition_weight_group fica None de proposito: aquele campo alimenta
    # national_team_profile_service.WEIGHTS, que e' indexado direto
    # (WEIGHTS[comp_type]) -- string nova ali viraria KeyError no fluxo de
    # selecao. O peso de copa de clube e' cross_competition_weight, abaixo.
    73: CompetitionProfile(73, "CLUB_CUP", neutral_venue=False, is_national_team=False),
    13: CompetitionProfile(13, "CLUB_CUP", neutral_venue=False, is_national_team=False),
    # AS OUTRAS CINCO COPAS DE CLUBE QUE O MOTOR JA' AVALIA (2026-08-13).
    #
    # 2/3/848 estavam caindo no _DEFAULT (LEAGUE) e a 11 estava cadastrada como
    # QUALIFIERS de selecao. Nenhuma das duas coisas era decisao: as tres da
    # UEFA nunca foram cadastradas, e o 11 e' o mesmo erro do 39 corrigido em
    # 2026-08-01 -- id herdado de uma lista antiga sem conferir item a item.
    # Na API-Football 11 e' a CONMEBOL Sul-Americana, competicao de CLUBE. O
    # proprio _LEAGUE_PRIORITY dos pipelines lista "13: 12, 11: 13", Libertadores
    # e Sul-Americana lado a lado.
    #
    # O efeito de estar fora era o mesmo que motivou o CLUB_CUP em 2026-08-01:
    # fase de grupos da' 6 jogos no teto e o mata-mata da' 1 a 4, entao o
    # historico travado na propria competicao nao alcanca o minimo de 5 de
    # data_validation.validate_history e a fixture inteira e' descartada em
    # silencio. Com a 11 havia ainda o efeito torto de tratar clube como
    # selecao em classify_competition_weight_group e no perfil de selecao.
    11:  CompetitionProfile(11,  "CLUB_CUP", neutral_venue=False, is_national_team=False),
    2:   CompetitionProfile(2,   "CLUB_CUP", neutral_venue=False, is_national_team=False),
    3:   CompetitionProfile(3,   "CLUB_CUP", neutral_venue=False, is_national_team=False),
    848: CompetitionProfile(848, "CLUB_CUP", neutral_venue=False, is_national_team=False),
}

# Peso do jogo conforme a competicao de ORIGEM, usado ao montar historico
# multi-competicao. Um 4x0 na Copa do Brasil contra time de divisao inferior
# nao vale o mesmo que 4x0 no Brasileirao -- sem isso, abrir o historico pra
# todas as competicoes trocaria "amostra pequena" por "amostra enviesada".
#
# Ainda NAO esta conectado ao calculo: entra junto com a ponderacao no
# stats_model, que e' mudanca de Score Final e exige o registro de impacto
# que o usuario pediu antes de mexer em Score Final.
_CROSS_COMPETITION_WEIGHT: dict[int, float] = {
    71: 1.00,   # Brasileirao A -- referencia
    72: 0.85,   # Brasileirao B
    13: 1.00,   # Libertadores -- nivel comparavel a Serie A
    73: 0.75,   # Copa do Brasil -- entra time de divisao inferior
    11: 0.80,   # Sul-Americana -- nivel abaixo da Libertadores
    2:  1.00,   # Champions
    3:  0.85,   # Europa League
    848: 0.75,  # Conference -- entra clube de liga menor
}
_DEFAULT_CROSS_WEIGHT = 0.80
for _qid in _QUALIFIERS_IDS:
    _PROFILES[_qid] = CompetitionProfile(
        _qid, "QUALIFIERS", neutral_venue=False, is_national_team=True, competition_weight_group="Eliminatórias"
    )

# Liga desconhecida (nao cadastrada acima): mesmo fallback que
# ai/prompts/_default.py ja usa hoje -- liga generica, mando normal, nao selecao.
_DEFAULT = CompetitionProfile(-1, "LEAGUE", neutral_venue=False, is_national_team=False)


def get_profile(league_id) -> CompetitionProfile:
    return _PROFILES.get(league_id, _DEFAULT)


def is_national_team_league(league_id) -> bool:
    return get_profile(league_id).is_national_team


def is_club_cup(league_id) -> bool:
    return get_profile(league_id).type == "CLUB_CUP"


def uses_all_competitions_history(league_id) -> bool:
    """Historico deve vir de TODAS as competicoes do time, nao so' desta.

    Vale pra selecao (sempre valeu) e agora tambem pra copa de clube. O
    motivo e' o mesmo nos dois casos: a competicao em si nao acumula jogo
    suficiente. Selecao joga pouco por natureza; mata-mata idem. Travar o
    historico na propria competicao faz validate_history reprovar a fixture
    inteira, em silencio -- o pick nunca aparece e nada indica o porque.
    """
    perfil = get_profile(league_id)
    return perfil.is_national_team or perfil.type == "CLUB_CUP"


def cross_competition_weight(league_id) -> float:
    """Peso do jogo pela competicao de origem, ao misturar historico."""
    return _CROSS_COMPETITION_WEIGHT.get(league_id, _DEFAULT_CROSS_WEIGHT)


def is_neutral_venue(league_id) -> bool:
    return get_profile(league_id).neutral_venue


def competition_weight_group(league_id) -> str | None:
    return get_profile(league_id).competition_weight_group


# ============================================================
# Helpers de derivacao -- consumidos pelos modulos que antes mantinham
# a propria lista/constante (ver Prioridade 1 do plano de refatoracao).
# ============================================================
def national_team_league_ids() -> frozenset:
    """Substitui match_stats_service.NATIONAL_TEAM_LEAGUE_IDS -- mesmo
    conjunto de sempre, agora derivado de _PROFILES em vez de mantido em
    paralelo."""
    return frozenset(lid for lid, p in _PROFILES.items() if p.is_national_team)


def neutral_venue_league_ids() -> frozenset:
    """Substitui ai_suggestions_service.NEUTRAL_VENUE_LEAGUES."""
    return frozenset(lid for lid, p in _PROFILES.items() if p.neutral_venue)


def classify_competition_weight_group(league_id) -> str:
    """Substitui national_team_profile_service._classify_competition().
    Fallback identico ao original: liga sem grupo de peso definido cai em
    'Amistoso/Outra'."""
    return competition_weight_group(league_id) or "Amistoso/Outra"


# ============================================================
# Prioridade 4: fase da partida a partir do campo round da API-Football
# (fixtures.round, coletado por fixture_collector_service -- so existe pra
# jogos NS, a tabela fixtures e efemera). Isso e por FIXTURE, nao por liga --
# uma mesma competicao tem GROUP_STAGE e KNOCKOUT_* em partes diferentes do
# calendario, por isso fica fora do CompetitionProfile (que e estatico por
# league_id) e vira uma funcao separada que le o texto do round.
_KNOCKOUT_SINGLE_KEYWORDS = (
    "round of", "quarter", "semi", "final", "play-off", "playoff", "third place",
)


def classify_round_phase(round_str: str | None, formato: str | None = None) -> str | None:
    """GROUP_STAGE | KNOCKOUT_SINGLE | KNOCKOUT_TWO_LEGS a partir do texto
    round da API-Football (ex.: "Group Stage - 3", "Round of 16", "Semi-
    finals", "Final - 1st Leg"). "leg" e checado ANTES de knockout-single
    pra cobrir finais/semis de ida-e-volta corretamente (ex.: "Final - 1st
    Leg" nao pode cair em KNOCKOUT_SINGLE). None quando o texto nao bate em
    nenhum padrao conhecido -- nunca advinha.

    `formato` (2026-08-19) e' o formato JA RESOLVIDO da partida, saida de
    match_context_model.resolver_formato() -- que sabe coisas que o texto do
    round nao diz. Medido em producao no mesmo dia: a API-Football manda
    "Round of 16" seco pras oitavas de Libertadores e Sul-Americana, sem
    "1st leg"/"2nd leg", e essa funcao classificava as 34 picks ja' gravadas
    no picks_ledger como KNOCKOUT_SINGLE -- nenhuma linha do ledger tinha
    KNOCKOUT_TWO_LEGS, num universo em que TODAS as oitavas dessas duas
    competicoes sao de ida e volta. O rotulo errado nao muda so' o relatorio:
    round_phase e' dimensao de segmentacao em attribution.py, entao jogo unico
    e volta de mata-mata estavam sendo somados no mesmo balde de calibracao.

    Quando o formato vem resolvido, ele MANDA -- ele saiu de evidencia
    (rotulo com perna, ou o confronto anterior com o mando invertido), nao de
    palpite sobre o texto.
    """
    if formato == "COPA_IDA_E_VOLTA":
        return "KNOCKOUT_TWO_LEGS"
    if formato == "COPA_JOGO_UNICO":
        return "KNOCKOUT_SINGLE"
    if not round_str:
        return None
    name = round_str.strip().lower()
    if "leg" in name:
        return "KNOCKOUT_TWO_LEGS"
    if "group" in name:
        return "GROUP_STAGE"
    if any(kw in name for kw in _KNOCKOUT_SINGLE_KEYWORDS):
        return "KNOCKOUT_SINGLE"
    return None


# ============================================================
# REGULAMENTO DE MATA-MATA (2026-08-19)
#
# "NAO assuma regra de gol fora. A regra deve ser obtida da competicao ou
# configuracao correspondente." -- e' o pedido, e a estrutura abaixo existe
# pra tornar impossivel desobedecer: `away_goals` e' um TRI-ESTADO. None
# significa "nao declarado", nao "nao tem", e nenhum calculo deste motor
# aplica aritmetica de gol fora a menos que o campo seja True literal.
#
# O mesmo vale pro formato: `two_legged_default=None` quer dizer que o
# regulamento nao esta cadastrado, e nesse caso quem decide se ha ida e volta
# e' a EVIDENCIA do confronto (ver match_context_model.resolver_formato), nunca
# o fato de a competicao se chamar copa.
# ============================================================
@dataclass(frozen=True)
class RegrasDeMataMata:
    #: True/False = regulamento cadastrado. None = nao declarado; o formato
    #: tem que sair da evidencia do confronto.
    two_legged_default: bool | None
    #: Fases que fogem do padrao da competicao (a final unica da CONMEBOL e da
    #: UEFA num torneio cujo resto e' ida e volta).
    fases_de_jogo_unico: frozenset
    #: Tri-estado. So' True autoriza qualquer conta de gol fora.
    away_goals: bool | None
    prorrogacao: bool | None
    penaltis: bool | None


_REGRAS_PADRAO = RegrasDeMataMata(
    two_legged_default=None, fases_de_jogo_unico=frozenset(),
    away_goals=None, prorrogacao=None, penaltis=None,
)

# Regulamentos cadastrados. Cada linha e' uma afirmacao sobre o regulamento
# REAL da competicao -- se ele mudar, muda aqui, e nao espalhado no motor.
#
# away_goals=False nas cinco: a UEFA aboliu o criterio a partir de 2021/22 e a
# CONMEBOL a partir de 2024. Ficam False (declarado que NAO vale), nao None.
_REGRAS: dict[int, RegrasDeMataMata] = {
    # CONMEBOL -- mata-mata em ida e volta, final em jogo unico desde 2019.
    13:  RegrasDeMataMata(True, frozenset({"FINAL"}), False, True, True),
    11:  RegrasDeMataMata(True, frozenset({"FINAL"}), False, True, True),
    # UEFA -- mesmo desenho: eliminatorias em duas pernas, final unica.
    2:   RegrasDeMataMata(True, frozenset({"FINAL"}), False, True, True),
    3:   RegrasDeMataMata(True, frozenset({"FINAL"}), False, True, True),
    848: RegrasDeMataMata(True, frozenset({"FINAL"}), False, True, True),
    # Copa do Brasil -- ida e volta INCLUSIVE na final, e sem prorrogacao:
    # empate no agregado vai direto pros penaltis.
    73:  RegrasDeMataMata(True, frozenset(), False, False, True),
    # Copa do Mundo -- mata-mata inteiro em jogo unico.
    1:   RegrasDeMataMata(False, frozenset(), False, True, True),
}


def regras_de_mata_mata(league_id) -> RegrasDeMataMata:
    """Regulamento cadastrado da competicao. Competicao nao cadastrada devolve
    tudo None -- "nao sei", que e' diferente de "nao tem"."""
    return _REGRAS.get(league_id, _REGRAS_PADRAO)


def formato_declarado(league_id, fase: str | None) -> str | None:
    """COPA_IDA_E_VOLTA | COPA_JOGO_UNICO pelo REGULAMENTO, ou None quando ele
    nao esta cadastrado. E' a ultima fonte consultada por
    match_context_model.resolver_formato -- evidencia do confronto vem antes.
    """
    regras = regras_de_mata_mata(league_id)
    if regras.two_legged_default is None:
        return None
    if fase and fase in regras.fases_de_jogo_unico:
        return "COPA_JOGO_UNICO"
    return "COPA_IDA_E_VOLTA" if regras.two_legged_default else "COPA_JOGO_UNICO"
