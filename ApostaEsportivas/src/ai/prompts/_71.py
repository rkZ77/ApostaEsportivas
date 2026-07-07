# Brasileirão Série A (ID 71)
from ai.prompts._base import build_prompt

LEAGUE_CONTEXT = """\
════════════════════════════════════════════════════════════════
CONTEXTO DA COMPETIÇÃO · BRASILEIRÃO SÉRIE A (ID 71) | Season 2026
════════════════════════════════════════════════════════════════

PERFIL ESTATÍSTICO DE REFERÊNCIA:
  Gols/jogo          : 2.3 – 2.5 (média histórica da liga)
  BTTS               : 44 – 48%
  Cantos/jogo        : 9 – 10
  Amarelos/jogo      : 4.0 – 4.5 (maior que ligas europeias · mercado mais sólido desta liga)
  Vermelhos/jogo     : 0.25
  Vantagem casa      : ~60% vitórias (uma das mais altas do futebol organizado)

FATORES CONTEXTUAIS PERMANENTES:
  · Torcida e pressão local são determinantes · não subestime a vantagem em casa
  · Distâncias geográficas enormes geram fadiga real nos times visitantes
  · Times no Z4 (rebaixamento) elevam intensidade física → mais faltas, mais cartões
  · Times no G4/G6 (Libertadores) priorizam pontos em casa acima de tudo
  · Times recém-rebaixados da Série A costumam ter elenco acima da média no início da temporada
  · Árbitros brasileiros são mais rigorosos com cartões do que a média europeia

CONDIÇÕES DE CONFIABILIDADE POR MERCADO:
  CARTÕES   → requer árbitro com avg_yellow > 4.0 E histórico dos dois times > 3.5 amarelos/jogo (ambas as condições)
  RESULTADO → requer dados de forma e standing sólidos; alta variância quando equilíbrio de pontos
  GOLS      → amostra mínima: soma de médias > 2.5; abaixo disso, incerteza alta
  BTTS      → requer evidência em ambos os times (taxa > 55% em cada time)
  HANDICAP  → requer rank_diff > 8 com dados históricos consistentes
  CANTOS    → requer média > 5.0 cantos/jogo no time analisado

PROTOCOLO PARA DADOS ESCASSOS NESTA LIGA:
  Com amostra ESCASSO/VAZIO: standings (posição, pontos, forma) são indicadores robustos.
  G4 em casa vs. Z4 visitante com amostra escassa → resultado home tem evidência mais sólida.
  Para cartões sem histórico: use a média da liga (4.2/jogo) como referência base.
"""

PROMPT = build_prompt(LEAGUE_CONTEXT)
