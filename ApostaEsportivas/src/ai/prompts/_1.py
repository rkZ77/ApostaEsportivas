# Copa do Mundo FIFA (ID 1)
from ai.prompts._base import build_prompt

LEAGUE_CONTEXT = """\
CONTEXTO — COPA DO MUNDO FIFA 2026 (league_id=1)

BASELINE: Gols/jogo: grupos=2.5–2.8 | mata-mata=2.0–2.3 | Over 1.5: grupos=82–88% | mata-mata=72–78% | Over 2.5: grupos=52–58% | mata-mata=38–45% | Under 3.5 mata-mata=85–90% | Cantos=9–10/jogo | Amarelos=2.5–3.0 (VAR conservador) | Vermelhos=raros (<0.12)

RANKING FIFA (primário quando histórico<3 jogos):
  Diff>40: favorito domina → Handicap -1 ou Dupla Chance viáveis
  Diff 20-40: vantagem clara → Dupla Chance ou Over 1.5
  Diff<20: equilibrado → evite resultado puro, prefira gols/cantos
  Top-10 vs abaixo #50: desequilíbrio máximo

FASE:
  Grupos r1-r2: times precisam de pontos → mais abertos | r3: resultados combinados possíveis → evite resultado puro
  Mata-mata: tático → Over 2.5 perde edge; Over 1.5 e Under 3.5 preferíveis; pênaltis frequentes em equilíbrio

POR MERCADO:
  Over 1.5→baixo risco grupos | Over 2.5→grupos ofensivos, reduzir no mata-mata | Under 3.5→seguro mata-mata
  BTTS Sim→ambas BTTS>50% grupos | BTTS Não→mata-mata com ataque fraco | Cartões→nunca vermelho | Handicap→diff FIFA>30
  Resultado→sólido top-10 vs #50+ r1-r2; EVITAR r3 e mata-mata equilibrado

DADOS ESCASSOS: Ranking FIFA + forma recente. Baseline 2.6 gols/jogo grupos. Não use dados de qualificatórias.
"""

PROMPT = build_prompt(LEAGUE_CONTEXT)
