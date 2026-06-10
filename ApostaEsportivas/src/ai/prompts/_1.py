# Copa do Mundo FIFA (ID 1)
from ai.prompts._base import build_prompt

LEAGUE_CONTEXT = """\
════════════════════════════════════════════════════════════════
CONTEXTO DA COMPETIÇÃO — COPA DO MUNDO FIFA (ID 1) | Season 2026
════════════════════════════════════════════════════════════════

PERFIL ESTATÍSTICO DE REFERÊNCIA:
  Gols/jogo (grupos)   : 2.5 – 2.8
  Gols/jogo (mata-mata): 2.0 – 2.3
  BTTS (grupos)        : 48 – 52%
  BTTS (mata-mata)     : 40 – 44%
  Over 1.5 gols        : 82 – 88% (grupos) | 72 – 78% (mata-mata)
  Over 2.5 gols        : 52 – 58% (grupos) | 38 – 45% (mata-mata)
  Under 3.5 gols       : 85 – 90% (mata-mata — padrão fechado)
  Cantos/jogo          : 9 – 10
  Amarelos/jogo        : 2.5 – 3.0 (árbitros FIFA com VAR são conservadores)
  Vermelhos/jogo       : 0.08 – 0.12 (raros — VAR elimina erros grosseiros)

RANKING FIFA — USO OBRIGATÓRIO QUANDO HISTÓRICO É ESCASSO:
  Diferença > 40 posições : favorito domina — Handicap -1 ou Resultado direto viáveis
  Diferença 20-40 posições: vantagem clara mas não total — Dupla Chance ou Over 1.5 preferíveis
  Diferença < 20 posições : jogo equilibrado — evite resultado puro, prefira gols/cantos
  Top-10 FIFA vs. abaixo #50: desequilíbrio máximo — todos os mercados do favorito viáveis

FATORES CONTEXTUAIS PERMANENTES:
  — Ranking FIFA é o indicador primário quando histórico do torneio tem < 3 jogos por time
  — Fase de grupos r1-r2: times precisam de pontos → jogos mais abertos
  — Fase de grupos r3: resultados combinados possíveis → evitar mercados de resultado puro
  — Mata-mata: intensidade tática máxima → Over 2.5 tem edge reduzido; Over 1.5 e Under 3.5 preferíveis
  — VAR elimina erros grosseiros → nunca aposte em Mais de 0.5 cartões vermelhos
  — Pênaltis no mata-mata são frequentes em jogos tecnicamente equilibrados

INTERPRETAÇÃO CONTEXTUAL POR MERCADO:
  HANDICAP     → válido com diferença de Ranking FIFA > 30 posições; risco alto em mata-mata
  RESULTADO    → sólido: top-10 FIFA vs. abaixo #50, grupos r1-r2; EVITAR em grupos r3 e mata-mata equilibrado
  OVER 1.5     → mercado de baixo risco em grupos; taxa histórica 82-88%; válido salvo ambas as defesas top-10
  OVER 2.5     → grupos r1-r2 com ambas seleções ofensivas; reduzir confiança no mata-mata
  UNDER 2.5    → mata-mata: taxa histórica 55-62%; válido quando ambas top-15 FIFA
  UNDER 3.5    → alta segurança no mata-mata (85-90%); válido em grupos r3 com times conservadores
  BTTS SIM     → grupos: válido quando ambas com BTTS > 50% no histórico recente
  BTTS NÃO     → mata-mata: válido quando um time tem ataque fraco (Ranking FIFA > 40) ou Under 2.5 esperado
  CARTÕES      → Over amarelos válido em jogos físicos ou rivalidades históricas; nunca vermelho
  CANTOS       → favorito com estilo de pressão alta e diferença > 25 posições FIFA

PROTOCOLO PARA DADOS ESCASSOS:
  Início do torneio (0-2 jogos): Ranking FIFA + forma recente são os únicos indicadores confiáveis.
  Média da liga (2.6 gols/jogo grupos) serve como baseline; não use dados de qualificatórias.
  Mata-mata sem histórico no torneio: assuma fechamento tático — Over 2.5 perde edge automaticamente.
"""

PROMPT = build_prompt(LEAGUE_CONTEXT)
