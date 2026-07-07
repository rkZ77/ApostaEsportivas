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
_QUALIFIERS_IDS = {31, 32, 33, 34, 35, 36, 37, 38, 39, 882, 780}

_PROFILES: dict[int, CompetitionProfile] = {
    1:  CompetitionProfile(1,  "INTERNATIONAL_TOURNAMENT", neutral_venue=True,  is_national_team=True, competition_weight_group="Copa do Mundo"),
    9:  CompetitionProfile(9,  "INTERNATIONAL_TOURNAMENT", neutral_venue=False, is_national_team=True, competition_weight_group="Amistoso/Outra"),
    4:  CompetitionProfile(4,  "INTERNATIONAL_TOURNAMENT", neutral_venue=False, is_national_team=True, competition_weight_group="Amistoso/Outra"),
    14: CompetitionProfile(14, "INTERNATIONAL_TOURNAMENT", neutral_venue=False, is_national_team=True, competition_weight_group="Amistoso/Outra"),
    23: CompetitionProfile(23, "INTERNATIONAL_TOURNAMENT", neutral_venue=False, is_national_team=True, competition_weight_group="Amistoso/Outra"),
    10: CompetitionProfile(10, "FRIENDLY",                 neutral_venue=False, is_national_team=True, competition_weight_group="Amistoso/Outra"),
    11: CompetitionProfile(11, "QUALIFIERS",               neutral_venue=False, is_national_team=True, competition_weight_group="Amistoso/Outra"),
    71: CompetitionProfile(71, "LEAGUE", neutral_venue=False, is_national_team=False),
    72: CompetitionProfile(72, "LEAGUE", neutral_venue=False, is_national_team=False),
}
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
