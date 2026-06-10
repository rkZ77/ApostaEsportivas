-- Adiciona coluna referee na match_statistics
-- Necessário porque a tabela fixtures deleta jogos finalizados,
-- então referee_stats não conseguia fazer o JOIN para calcular médias.
ALTER TABLE match_statistics ADD COLUMN IF NOT EXISTS referee VARCHAR(255);
