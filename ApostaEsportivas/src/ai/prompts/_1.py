# Copa do Mundo FIFA (ID 1)
from ai.prompts._base import build_prompt

LEAGUE_CONTEXT = """\
CONTEXTO — COPA DO MUNDO FIFA 2026 (league_id=1)

SEDE NEUTRA (OVERRIDE OBRIGATÓRIO):
  Copa do Mundo é disputada em campo neutro. Não existe vantagem de mando.
  IGNORE a instrução "casa se mandante, fora se visitante" do prompt base.
  Para TODOS os mercados: use os dados TOTAIS de cada seleção como amostra única (histórico casa e fora unificados).
  Declare no reasoning: "Copa: sede neutra — usando dados totais sem filtro de mando."

BASELINE Copa 2026 (referência estatística — não use como confirmador isolado):
  Gols/jogo: grupos=2.5–2.8 | mata-mata=2.0–2.3
  Cantos=9–10/jogo | Amarelos=2.5–3.0 (VAR conservador) | Vermelhos=raros (<0.12)
  Use como contexto de calibração; exija dados específicos dos dois times antes de apostar.

PONDERAÇÃO POR COMPETIÇÃO (OBRIGATÓRIO para seleções nacionais):
  Pesos: Copa do Mundo=3x | Eliminatórias Competitivas=2x | Amistoso/Outra=0.5x
  O campo "quality_breakdown" no perfil de cada seleção já mostra stats por tipo de competição.
  Use a média PONDERADA (weighted_goals_against, etc.) em vez da média bruta.
  Declare no reasoning qual % dos dados veio de jogos Copa/Eliminatórias vs amistosos.
  Ex: "Morocco: bruto 0.36 gols sofridos/j (15j) → ponderado 0.48 (8j Elim + 2j Copa + 5j amistosos)"

RANKING FIFA (primário quando histórico<3 jogos competitivos):
  Diff>40: desequilíbrio forte — analise mercados de desequilíbrio (handicap, gols por time)
  Diff 20-40: vantagem clara — analise todos os mercados, favoritismo influencia probabilidades
  Diff<20: equilíbrio — resultado puro tem alta variância; prefira mercados de volume (gols/cantos totais)
  Top-10 vs abaixo #50: desequilíbrio máximo — exija dados robustos do time fraco

FASE:
  Grupos r1-r2: times precisam de pontos → mais pressionados, mais abertos
  r3: resultados combinados possíveis → resultado puro tem variância altíssima
  Mata-mata: contexto tático — intensidade defensiva maior; analise o histórico específico

CARTÕES: NUNCA aposte em vermelho.
  O baseline 2.5–3.0 amarelos/jogo é média da competição — variância jogo-a-jogo é ALTA.
  NÃO use o baseline como confirmador: exija histórico específico dos dois times E do árbitro.
  Sem ambos → cartões tem volatilidade MÉDIA e NÃO deve ser is_best_pick.

DADOS ESCASSOS: Ranking FIFA + forma recente. Baseline 2.6 gols/jogo grupos.
"""

PROMPT = build_prompt(LEAGUE_CONTEXT)
