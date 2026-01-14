"""
Modelo estatístico para gols usando Poisson.
"""
import numpy as np
from scipy.stats import poisson


def prob_goals_total(avg_home, avg_away, line):
    lamb = avg_home + avg_away
    prob = 1 - poisson.cdf(line, lamb)
    return prob


def prob_goals_team(avg, line):
    prob = 1 - poisson.cdf(line, avg)
    return prob
