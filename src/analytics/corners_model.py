"""
Modelo estatístico para escanteios.
"""
import numpy as np


def prob_corners_total(avg_home, avg_away, line):
    avg = avg_home + avg_away
    var = max(avg, 1)
    prob = 1 - np.exp(-((line - avg)**2) / (2 * var))
    return prob


def prob_corners_team(avg, line):
    var = max(avg, 1)
    prob = 1 - np.exp(-((line - avg)**2) / (2 * var))
    return prob
