-- Migration: inclui line_value na chave única de odds_values
--
-- Problema: ON CONFLICT (market_row_id, value_name) armazenava apenas
-- uma linha por direção por bookmaker+mercado. Para mercados com múltiplas
-- linhas (Over 0.5, Over 1.5, Over 2.5...), só a última da API ficava
-- gravada — aleatório conforme ordem de resposta.
--
-- Solução: nova constraint inclui line_value, armazenando todas as linhas.
-- Seguro rodar mesmo com dados no banco (capturar_odds faz TRUNCATE antes).

BEGIN;

-- Remove a constraint antiga (tenta os dois nomes possíveis)
ALTER TABLE odds_values DROP CONSTRAINT IF EXISTS odds_values_market_row_id_value_name_key;
ALTER TABLE odds_values DROP CONSTRAINT IF EXISTS odds_values_market_value_line_key;

-- Remove possíveis duplicatas caso o banco tenha dados (segurança)
DELETE FROM odds_values a
USING odds_values b
WHERE a.id > b.id
  AND a.market_row_id = b.market_row_id
  AND a.value_name    = b.value_name
  AND a.line_value    = b.line_value;

-- Cria nova constraint incluindo line_value
ALTER TABLE odds_values
    ADD CONSTRAINT odds_values_market_value_line_key
    UNIQUE (market_row_id, value_name, line_value);

COMMIT;
