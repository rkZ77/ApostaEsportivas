---
name: blog-post
description: Escreve e publica um artigo novo no blog do Pick IA (website/frontend/src/blog). Use quando o usuário disser "/blog-post", "escreva um artigo", "novo post do blog", ou passar um tema/keyword para o blog. Argumento opcional: tema ou palavra-chave.
---

# Blog Post — Pick IA

Gera um artigo completo de SEO/GEO para o blog do Pick IA, do zero até um Pull Request pronto
para revisão. Siga os passos na ordem. Não pule etapas mesmo em execução automática (cron).

## Passo 1 — Ler a estratégia

Leia por inteiro `website/frontend/src/blog/DNA.md`. Esse arquivo define produto, público, tom
de voz, keywords e regras de SEO — é a fonte de verdade, não improvise por cima dele.

Se as skills `seo-geo` e `humanizer` existirem em `.claude/skills/`, leia-as também: `seo-geo`
para otimização de estrutura/keywords, `humanizer` para os sinais de texto com "cara de IA" que
você vai precisar eliminar no Passo 4.

## Passo 2 — Escolher o tema

Leia os artigos já publicados olhando os arquivos em `website/frontend/src/blog/content/*.meta.ts`
(cada um exporta `meta.title` e `meta.slug`) para não repetir tema.

- Se foi passado um argumento (tema ou keyword), use-o como base, ajustando à lista de
  keywords primárias do DNA.
- Se não foi passado nada, escolha um tema novo seguindo a distribuição de pilares do DNA
  (prioridade alta antes de prioridade baixa), evitando repetir pilar do último artigo publicado.

Defina antes de escrever: keyword primária, título (até ~65 caracteres), slug (kebab-case, com
a keyword), description (140-160 caracteres, com a keyword) e categoria.

## Passo 3 — Escrever o artigo

Crie **dois arquivos** em `website/frontend/src/blog/content/`, copiando o par
`kelly-criterion-apostas-esportivas.meta.ts` + `kelly-criterion-apostas-esportivas.tsx` como
modelo. São dois arquivos (não um só) de propósito: o registry importa todos os `.meta.ts` de
forma eager para listar os posts sem baixar o corpo de nenhum artigo, e os `.tsx` de forma
lazy para o componente virar um chunk separado por artigo. Se meta e componente ficarem no
mesmo arquivo, o bundler junta tudo em um chunk só e a página `/blog` passa a baixar o texto
de todo artigo publicado — não faça isso.

**`<slug>.meta.ts`** — exporta só `meta: PostMeta` (import de `../types`): `slug`, `title`,
`description`, `publishedAt` (data de hoje, formato `YYYY-MM-DD`), `readingTime` (~200
palavras/minuto), `category`, `author` (`{ name: 'Equipe Pick IA', role: 'Conteúdo e Análise' }`).

**`<slug>.tsx`** — exporta só o componente default, sem `meta`. Usa **apenas** as primitivas de
`website/frontend/src/blog/article-ui.tsx`: `P`, `H2`, `H3`, `UL`, `OL`, `LI`, `Strong`,
`Quote`, `Callout`. Nunca escreva HTML ou classes Tailwind cru dentro do artigo.

- 900 a 1500 palavras. Estrutura: introdução (o problema/dúvida do leitor), 3 a 6 seções `H2`,
  conclusão que leva a `/planos` ou `/login?mode=register` via `<Link>` do `react-router-dom`
  (siga o exemplo do artigo modelo).
- Siga o tom, as regras de compliance (nunca prometer ganho garantido, aposta envolve risco) e
  as regras de SEO por artigo definidas no DNA.
- Inclua uma seção com lista numerada (`OL`) ou lista prática (`UL`) — importante para GEO.
- Se já existir outro artigo publicado sobre tema relacionado, linke para ele com `<Link>`.

Criar esses dois arquivos já é suficiente para o artigo aparecer no blog: o registry
(`website/frontend/src/blog/registry.ts`) descobre `content/*.meta.ts` e `content/*.tsx`
automaticamente via `import.meta.glob`, casando os dois pelo slug do nome do arquivo. Não
precisa editar o registry.

## Passo 4 — Humanizar

Releia o corpo do artigo e reescreva eliminando:
- Travessão (`—`/`–`) — trocar por `·` ou reescrever a frase.
- Emoji — nunca usar.
- Linguagem de "cara de IA": "no cenário atual", "vale ressaltar", "em suma", "mergulhe",
  "desbloqueie", "eleve", paralelismos do tipo "não é só X, é Y", voz passiva excessiva,
  aberturas/conclusões genéricas.
- Números, estatísticas ou depoimentos inventados. Exemplos numéricos ilustrativos (ex.: "banca
  de R$ 1.000") são aceitáveis desde que fique claro que é exemplo, não dado real.
- Promessa de lucro garantido — sempre compatível com "aposta envolve risco, aposte com
  responsabilidade".

Varie o comprimento das frases. Se a skill `humanizer` existir, siga o checklist dela.

## Passo 5 — Registrar

Nada a fazer além do Passo 3 — a descoberta do artigo é automática via `import.meta.glob`.

Adicione manualmente uma entrada em `website/frontend/public/sitemap.xml`, seguindo o padrão
das entradas de `/blog/<slug>` já existentes (`changefreq: monthly`, `priority: 0.6`). Esse
arquivo não é gerado automaticamente no build deste projeto.

## Passo 6 — Validar

Rode o build do frontend a partir de `website/frontend`:

```
npm run build
```

Confirme que passa sem erros de TypeScript. Depois releia o artigo final conferindo:
- Keyword primária no título, description, primeiro parágrafo e em pelo menos um H2.
- Nenhum travessão, nenhum emoji.
- Nenhum número ou depoimento inventado apresentado como fato real.
- Links internos (`<Link>`) válidos, apontando para rotas que existem (`/planos`,
  `/login?mode=register`, `/banca`, `/blog/<slug>` de outro artigo, etc.).
- Entrada correspondente no `sitemap.xml`.

## Passo 7 — Entregar

Se o build falhar e não for possível corrigir, **não entregue**: pare e reporte o erro.

Se o build passou, entregue sempre por **Pull Request** (decisão fixa deste projeto, não
pergunte de novo em runtime):

1. `git checkout -b blog/<slug>`
2. `git add website/frontend/src/blog/content/<slug>.meta.ts website/frontend/src/blog/content/<slug>.tsx website/frontend/public/sitemap.xml`
   (adicione também `website/frontend/src/blog/DNA.md` só se você o editou nesta execução)
3. `git commit -m "blog: <título do artigo>"`
4. `git push -u origin blog/<slug>`
5. `gh pr create --title "blog: <título do artigo>" --body "<resumo: tema, keyword primária,
   slug, contagem de palavras>"`

Termine a resposta resumindo: tema e por quê, keyword primária, slug/URL (`/blog/<slug>`),
contagem de palavras e o link do PR criado.
