"""
Modelos de dados para features de partidas.
"""
from dataclasses import dataclass


@dataclass
class MatchFeatures:
    date: str
    home_team: str
    away_team: str
    home_stats: dict
    away_stats: dict
    odds: dict
