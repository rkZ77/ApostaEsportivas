-- ============================================================
-- SEED DE PICKS DE TESTE — rodar no banco DEV apenas
-- Cria 3 picks VIP de hoje: 1 pendente, 1 GREEN, 1 RED
-- ============================================================

-- Limpa picks VIP de hoje (para não duplicar se rodar de novo)
DELETE FROM picks_vip WHERE match_date = CURRENT_DATE;

INSERT INTO picks_vip (
    fixture_id, match_date,
    home_team_id, away_team_id,
    home_team_name, away_team_name,
    market, line, odd,
    bet_house, market_type,
    confidence, stake, stake_pct, ev,
    reasoning,
    result, profit
) VALUES
-- Pick 1: Pendente (sem resultado)
(
    9000001, CURRENT_DATE,
    100, 200,
    'Flamengo', 'Palmeiras',
    'Over 2.5 Gols', NULL, 1.85,
    'Bet365', 'goals',
    0.78, 2.00, 0.02, 0.043,
    'Ambas as equipes têm média acima de 1.5 gols por jogo nas últimas 5 partidas. Histórico de confrontos diretos aponta para jogos movimentados.',
    NULL, NULL
),
-- Pick 2: GREEN
(
    9000002, CURRENT_DATE,
    300, 400,
    'Real Madrid', 'Barcelona',
    'Ambas Marcam - Sim', NULL, 1.72,
    'Sportingbet', 'btts',
    0.82, 2.00, 0.02, 0.038,
    'El Clásico historicamente tem ambas as equipes marcando. Defesas instáveis nas últimas rodadas.',
    'GREEN', 0.72
),
-- Pick 3: RED
(
    9000003, CURRENT_DATE,
    500, 600,
    'Manchester City', 'Arsenal',
    'Under 3.5 Escanteios - 1º Tempo', NULL, 1.90,
    'Betano', 'corners',
    0.71, 1.00, 0.01, 0.029,
    'Primeiros tempos de City e Arsenal costumam ter volume moderado de escanteios quando o jogo é equilibrado taticamente.',
    'RED', -1.00
);

-- Confirma
SELECT id, home_team_name, away_team_name, market, odd, result
FROM picks_vip
WHERE match_date = CURRENT_DATE
ORDER BY id;
