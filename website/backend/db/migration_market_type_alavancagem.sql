-- Adiciona market_type_1 e market_type_2 em picks_alavancagem
-- para resolução determinística sem depender de keyword matching no texto do mercado
ALTER TABLE picks_alavancagem
    ADD COLUMN IF NOT EXISTS market_type_1 TEXT,
    ADD COLUMN IF NOT EXISTS market_type_2 TEXT;

-- Backfill de picks existentes com market_type derivado do texto do mercado
UPDATE picks_alavancagem SET
    market_type_1 = CASE
        WHEN LOWER(market_1) LIKE '%corner%' OR LOWER(market_1) LIKE '%escanteio%' THEN 'corners'
        WHEN LOWER(market_1) LIKE '%card%'   OR LOWER(market_1) LIKE '%cartão%'    THEN 'cards'
        WHEN LOWER(market_1) LIKE '%goal%'   OR LOWER(market_1) LIKE '%gol%'       THEN 'goals'
        WHEN LOWER(market_1) LIKE '%btts%'   OR LOWER(market_1) LIKE '%ambas%'     THEN 'btts'
        ELSE 'result'
    END
WHERE market_type_1 IS NULL AND market_1 IS NOT NULL;

UPDATE picks_alavancagem SET
    market_type_2 = CASE
        WHEN LOWER(market_2) LIKE '%corner%' OR LOWER(market_2) LIKE '%escanteio%' THEN 'corners'
        WHEN LOWER(market_2) LIKE '%card%'   OR LOWER(market_2) LIKE '%cartão%'    THEN 'cards'
        WHEN LOWER(market_2) LIKE '%goal%'   OR LOWER(market_2) LIKE '%gol%'       THEN 'goals'
        WHEN LOWER(market_2) LIKE '%btts%'   OR LOWER(market_2) LIKE '%ambas%'     THEN 'btts'
        ELSE 'result'
    END
WHERE market_type_2 IS NULL AND market_2 IS NOT NULL;
