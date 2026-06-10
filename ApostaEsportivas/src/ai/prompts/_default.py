# Prompt genérico — usado quando a liga não tem perfil específico cadastrado
from ai.prompts._base import build_prompt

LEAGUE_CONTEXT = """\
════════════════════════════════════════════════════════════════
CONTEXTO DA COMPETIÇÃO — GENÉRICA (sem perfil específico cadastrado)
════════════════════════════════════════════════════════════════

PERFIL ESTATÍSTICO DE REFERÊNCIA:
  Sem baseline definida para esta liga — use exclusivamente os dados fornecidos.
  Não assuma médias europeias nem sul-americanas sem evidência nos dados.

FATORES CONTEXTUAIS:
  — Analise somente com base nas estatísticas, médias agregadas, standings e odds fornecidos
  — Não importar padrões de outras ligas ou competições
  — Qualquer inferência deve estar ancorada em ao menos 1 dado numérico concreto dos dados

PROTOCOLO PARA DADOS ESCASSOS:
  Standings e médias agregadas são a única base válida quando histórico de jogos for ESCASSO/VAZIO.
  Confidence máximo neste cenário: 0.68.
  Declare explicitamente no reasoning quando a evidência for limitada.
"""

PROMPT = build_prompt(LEAGUE_CONTEXT)
