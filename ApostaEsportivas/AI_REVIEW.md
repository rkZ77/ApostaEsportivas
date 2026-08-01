# Revisao de picks por IA

O motor estatistico continua calculando probabilidade, EV, risco e stake. A
IA recebe apenas a selecao final e pode identificar contradicoes ou lacunas
de contexto; ela nunca cria mercado, odds ou percentual de confianca.

## Provider por pipeline

Decisao de 31/07/2026: cada fluxo usa um provedor diferente.

| Pipeline      | Provider padrao | Modelo                                  |
| ------------- | --------------- | --------------------------------------- |
| `dica`        | anthropic       | `claude-opus-5`                         |
| `alavancagem` | anthropic       | `claude-opus-5`                         |
| `vip`         | openai          | obrigatorio via env, sem padrao         |
| `multipla`    | openai          | obrigatorio via env, sem padrao         |
| `goleiros`    | openai          | obrigatorio via env, sem padrao         |

Nao existe modelo padrao pra OpenAI de proposito. Um ID errado faz a chamada
falhar, e como o gate falha aberto isso viraria "aprovado" em silencio. Sem
`AI_REVIEW_MODEL_VIP` / `AI_REVIEW_MODEL_MULTIPLA` definidos, o gate daquele
pipeline se desliga sozinho e avisa no log.

O pipeline de defesas de goleiro (`goleiros`) ainda nao existe. Quando for
escrito, basta chamar `review_gate("goleiros").apply(...)` e definir
`AI_REVIEW_MODEL_GOLEIROS`; o provider ja esta mapeado pra OpenAI.

## Variaveis de ambiente

Toda variavel segue a mesma cascata, do mais especifico pro mais generico:

```
AI_REVIEW_MODEL_VIP_PROD  ->  AI_REVIEW_MODEL_VIP  ->  AI_REVIEW_MODEL_PROD  ->  AI_REVIEW_MODEL
```

Ou seja: um `AI_REVIEW_PROVIDER=anthropic` global sobrescreve os padroes da
tabela acima e derruba a divisao por pipeline. Se quiser a divisao, **nao
defina `AI_REVIEW_PROVIDER` nem `AI_REVIEW_MODEL` sem sufixo.**

| Variavel                | Padrao          | Observacao                                    |
| ----------------------- | --------------- | --------------------------------------------- |
| `AI_REVIEW_MODE`        | `off`           | `off`, `shadow` ou `enforce`                  |
| `AI_REVIEW_PROVIDER`    | ver tabela      | `anthropic` ou `openai`                       |
| `AI_REVIEW_MODEL`       | ver tabela      | ID exato do modelo                            |
| `AI_REVIEW_EFFORT`      | `low`           | so Anthropic: `low` a `max`                   |
| `AI_REVIEW_MAX_TOKENS`  | `2000`          | piso de 500                                   |
| `AI_REVIEW_CACHE_HOURS` | `24`            |                                               |
| `AI_REVIEW_DAILY_LIMIT` | `15`            | contado **por pipeline**, nao global          |

Chaves: `ANTHROPIC_API_KEY` e `OPENAI_API_KEY`. Os SDKs so sao importados
quando o pipeline daquele provider vai chamar de verdade.

`AI_REVIEW_MAX_TOKENS` nao pode voltar pros 350 antigos: no Opus 5 o thinking
vem ligado por padrao e `max_tokens` limita thinking + resposta juntos, entao
350 trunca o JSON antes de fechar.

## Rollout seguro

Sete dias em `AI_REVIEW_MODE=shadow`. Ele chama a IA e grava o parecer, mas
nunca remove um pick. Depois compare os pareceres com os resultados em
`ai_pick_review_events` e so entao ligue `enforce`, um fluxo por vez.

Com `AI_REVIEW_MODE=off` (padrao), nao existe chamada nem custo de IA.

## O gate falha aberto, e isso e visivel

Falha de rede, chave ausente, conta sem credito ou resposta invalida mantem o
pick do motor, pra nao interromper os pipelines diarios. O evento fica gravado
com `status` = `unavailable`, entao da pra ver no painel a diferenca entre
"a IA aprovou" e "a IA nunca respondeu". Vale conferir isso antes de confiar
num periodo de shadow: uma sequencia longa de `unavailable` significa que o
gate nao revisou nada.

O gate e aplicado uma vez por selecao final em Dica do Dia, Multipla e
Alavancagem. No VIP ele roda **por jogo**, dentro do loop de fixtures, entao
um dia com muitos jogos consome varias chamadas e pode bater no teto diario.

## DEV e producao

O painel Admin exibe revisoes das ultimas 24 horas, vetos, cache e os ultimos
pareceres, a partir de `ai_pick_review_events` (sobrevive a restart e deploy
no Railway). Os comandos `dev_*` do painel enviam `AI_REVIEW_ENV=dev`; os de
producao usam `AI_REVIEW_ENV=prod`.

```env
AI_REVIEW_MODE_DEV=shadow
AI_REVIEW_DAILY_LIMIT_DEV=5
AI_REVIEW_MODE_PROD=shadow
AI_REVIEW_DAILY_LIMIT_PROD=15
```

As tabelas `ai_pick_reviews` e `ai_pick_review_events` entram por
`run_migrations()`, que nao roda sozinha no merge: sem
`DB_ENV=prod python main.py setup`, o painel responde `migration_pending`.
