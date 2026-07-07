# Brasileirão Série B (ID 72)
from ai.prompts._base import build_prompt

LEAGUE_CONTEXT = """\
════════════════════════════════════════════════════════════════
CONTEXTO DA COMPETIÇÃO · BRASILEIRÃO SÉRIE B (ID 72) | Season 2026
════════════════════════════════════════════════════════════════

PERFIL ESTATÍSTICO DE REFERÊNCIA:
  Gols/jogo          : 2.2 – 2.4 (ligeiramente abaixo da Série A)
  BTTS               : 40 – 45% (menor que Série A · defesas mais fechadas)
  Cantos/jogo        : 8 – 10
  Amarelos/jogo      : 4.0 – 5.0 (maior que Série A · liga mais física)
  Vermelhos/jogo     : 0.30 (árbitros mais rigorosos que na Série A)
  Vantagem casa      : ~62% vitórias (maior que Série A)

FATORES CONTEXTUAIS PERMANENTES:
  · Vantagem em casa é o fator mais forte desta liga · torcida e pressão local são determinantes
  · Times do G4 (acesso): organizados, focados em resultado, muito sólidos em casa
  · Times do Z4 (rebaixamento): desesperados, físicos, mais faltas, mais cartões, mais erros defensivos
  · Times recém-rebaixados da Série A tendem a dominar no início por qualidade de elenco superior
  · Qualidade técnica heterogênea: mais erros individuais, mas também dificuldade de criar chances claras
  · Viagens longas entre regiões afetam rendimento dos visitantes (fadiga cumulativa)

CONDIÇÕES DE CONFIABILIDADE POR MERCADO:
  CARTÕES   → requer árbitro com avg_yellow > 4.5 E histórico dos dois times > 4.0 amarelos/jogo (ambas as condições)
  RESULTADO → alta variância; requer dados de forma e standing sólidos
  GOLS      → soma de médias combinadas deve suportar a linha analisada; abaixo de 2.4/jogo incerteza alta
  BTTS      → requer evidência muito clara em ambos os times (taxa > 55% em cada)
  HANDICAP  → requer rank_diff > 10 com dados históricos consistentes
  CANTOS    → volume menor que Série A; requer média > 5.0/jogo no time analisado

PROTOCOLO PARA DADOS ESCASSOS NESTA LIGA:
  Com amostra ESCASSO/VAZIO: posição na tabela (G4 vs Z4) é o preditor mais forte disponível.
  Cartões: média da liga (4.5/jogo) serve como referência base quando histórico é insuficiente.
  BTTS com amostra escassa: assuma 42% como baseline da liga · não invente padrão sem dados.
"""

PROMPT = build_prompt(LEAGUE_CONTEXT)
