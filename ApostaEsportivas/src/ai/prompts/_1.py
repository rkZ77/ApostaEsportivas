# Copa do Mundo FIFA (ID 1)
from ai.prompts._base import build_prompt

LEAGUE_CONTEXT = """\
CONTEXTO — COPA DO MUNDO FIFA 2026 (league_id=1)

SEDE NEUTRA (regra específica Copa — prevalece sobre contexto geral):
  Copa do Mundo é disputada em campo neutro. Não existe vantagem de mando para nenhuma seleção.
  Para mercados de time específico: use os dados TOTAIS da seleção (casa e fora combinados) — não filtre por mando.
  A distinção casa/fora NÃO se aplica a esta competição. Trate ambas as seleções com dados totais.
  Declare no reasoning: "Copa: sede neutra — dados totais usados para ambas as seleções."

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

FASE ATUAL — ELIMINATÓRIA (a partir de 29/06/2026):
  A fase de grupos ENCERROU. O torneio está agora no mata-mata.
  Estrutura restante: Oitavas (16 avos) → Quartas → Semifinais → Final (+ 3º lugar).
  REGRAS DESTA FASE:
    - Empate no tempo normal vai para prorrogação (2×15 min) → pênaltis se necessário.
    - Não existe "resultado puro" com empate — considere sempre 3 desfechos: vitória A, vitória B, decisão por pênaltis.
    - Para handicap/ML, ajuste: equilíbrio tático é maior pois um empate classifica o adversário.
    - Intensidade defensiva é MAIOR que na fase de grupos → prefira UNDER em mercados de gols totais.
    - Volume de jogo (cantos, cartões) tende a ser maior em jogos tensos e de alta pressão.
    - Times eliminados da discussão de grupo costumam ter formação mais conservadora nesta fase.
  Baseline mata-mata: 2.0–2.3 gols/jogo (vs 2.5–2.8 grupos). Use 2.1 como referência central.
  Histórico Copa: ~30–35% dos jogos de mata-mata terminam em prorrogação.

CARTÕES: NUNCA aposte em vermelho.
  O baseline 2.5–3.0 amarelos/jogo é média da competição — variância jogo-a-jogo é ALTA.
  NÃO use o baseline como confirmador: exija histórico específico dos dois times E do árbitro.
  Sem ambos → cartões tem volatilidade MÉDIA e NÃO deve ser is_best_pick.

DADOS ESCASSOS: Ranking FIFA + forma recente. Baseline 2.1 gols/jogo (fase eliminatória).
"""

PROMPT = build_prompt(LEAGUE_CONTEXT)
