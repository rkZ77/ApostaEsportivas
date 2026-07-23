---
name: seo-geo
description: Checklist de otimização de SEO tradicional e GEO (chance de citação por assistentes de IA como ChatGPT, Perplexity, Gemini, Copilot, Claude) para artigos do blog. Use ao escrever ou revisar um artigo de blog, junto com a skill blog-post.
---

# SEO + GEO — checklist de otimização

Aplique este checklist depois de escrever o rascunho de um artigo (Passo 3/6 da skill
`blog-post`), antes de considerá-lo pronto.

## SEO tradicional

- **Uma keyword primária por artigo.** Presente em: título, slug, `description`, primeiro
  parágrafo, pelo menos um `H2`. Não force a keyword em todo parágrafo (keyword stuffing
  prejudica ranqueamento).
- **Título** até ~65 caracteres. Formato pergunta ("O que é...", "Como calcular...") ou
  instrucional ("Como fazer X").
- **Description** entre 140 e 160 caracteres, com a keyword, que funcione como resumo
  clicável (não é só um resumo interno, é o texto que aparece no Google).
- **Slug** curto, minúsculo, kebab-case, com a keyword, sem stopwords desnecessárias.
- **Hierarquia de headings** limpa: um `H1` (o título da página, gerado por `BlogPost.tsx`),
  `H2` para seções principais, `H3` só para subseções dentro de um `H2`. Nunca pule nível.
- **Internal linking**: linkar para 1-3 artigos relacionados do próprio blog e para páginas
  de produto relevantes (`/planos`, `/banca`, `/como-funciona`), sempre com texto âncora
  descritivo (nunca "clique aqui").
- **Tamanho**: 900-1500 palavras. Abaixo disso o Google tende a não considerar o conteúdo
  aprofundado o suficiente; acima disso, cai o engajamento mobile (público do Pick IA é
  majoritariamente mobile).

## GEO — otimização para IA generativa

Assistentes de IA extraem trechos curtos e autocontidos para citar como resposta. Para
aumentar a chance de citação:

- **Cada seção deve responder sozinha.** Um `H2` + os parágrafos logo abaixo dele devem fazer
  sentido mesmo sem o resto do artigo. Evite "como vimos acima" ou "conforme dito antes".
- **Abra seções conceituais com uma definição direta** ("X é..."), não com uma anedota ou
  pergunta retórica.
- **Listas numeradas para processos** (`OL`), listas simples para itens sem ordem (`UL`). IAs
  extraem passos numerados com muito mais frequência que parágrafos corridos.
- **Uma pergunta = uma seção.** Ao escolher os `H2`, pense nas perguntas reais que alguém
  faria a um assistente de IA sobre o tema (ver seção "Intenção GEO" do `DNA.md`) e responda
  cada uma em uma seção dedicada.
- **Evite ambiguidade numérica.** Se citar uma fórmula ou exemplo com números, defina cada
  variável explicitamente antes de usá-la (ver o artigo `kelly-criterion-apostas-esportivas`
  como modelo de como apresentar uma fórmula).
- **JSON-LD `BlogPosting`** já é gerado automaticamente por `BlogPost.tsx` — não precisa
  adicionar manualmente, só garantir que `meta.title`, `meta.description` e
  `meta.publishedAt` estão corretos, pois alimentam o schema.

## O que não fazer

- Não fabricar estatísticas, cases ou depoimentos para parecer mais "citável" — isso quebra
  confiança se a fonte for checada, e o Pick IA lida com apostas, onde credibilidade importa
  mais que volume de conteúdo.
- Não usar títulos clickbait desconectados do conteúdo real do artigo.
- Não duplicar keyword primária entre artigos diferentes — cada artigo mira uma keyword única
  (checar `POSTS` do registry antes de escolher).
