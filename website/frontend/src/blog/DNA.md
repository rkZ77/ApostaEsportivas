# DNA do Blog — Pick IA

Este arquivo é a fonte de verdade estratégica do blog. Leia por inteiro antes de escrever
qualquer artigo. Edite-o quando o posicionamento, o produto ou a estratégia de SEO mudarem.

## Quem somos

**Pick IA** (pickia.com.br) é uma plataforma que usa inteligência artificial para gerar
picks de apostas esportivas de futebol todos os dias, com base em dados estatísticos reais
(forma recente dos times, histórico de confrontos, odds de mercado).

Produtos dentro da plataforma:
- **Picks VIP** — picks diários com análise completa, publicados até às 12h, com raciocínio,
  odd, mercado e stake sugerido via Kelly Criterion.
- **Dica do Dia (Free)** — pick gratuito diário para quem ainda não é VIP testar a plataforma.
- **Múltiplas** — combinações de 2 a 4 picks selecionados pela IA, só montadas quando os jogos
  passam em critérios estatísticos rigorosos.
- **Alavancagem** — pick combinado (simples, dupla ou tripla) com odd entre 1.45 e 1.55,
  pensado para crescimento de banca com risco controlado.
- **Agente IA** — chat com uma IA especialista em futebol, disponível 24/7, que explica picks,
  mercados e odds sob demanda.
- **Minha Banca** — ferramenta de gestão de banca: registra apostas, calcula ROI e win rate,
  sugere stake pelo Kelly Criterion.
- **Resultados/Estatísticas públicas** — histórico transparente de performance da IA, filtrável
  por tipo de pick e período.

Planos: **Free** (Dica do Dia) e **VIP** (mensal, trimestral, anual — ver `/planos`), com
2 dias de trial VIP grátis no cadastro.

- URL de produto: `https://pickia.com.br`
- URL de cadastro: `/login?mode=register`
- URL de planos/conversão: `/planos`

## Público-alvo

- **Apostador iniciante** que já aposta por conta própria mas nunca formalizou gestão de banca,
  não sabe o que é EV positivo ou Kelly Criterion. Nível técnico: leigo. Nunca presumir que o
  leitor conhece jargão sem explicar.
- **Apostador intermediário** que já usa alguma estratégia mas quer decisões mais consistentes
  e menos emocionais — público natural para picks de IA.
- **Usuário Free do Pick IA** avaliando se vale virar VIP — o blog é uma ponte de educação até
  a conversão, não apenas um canal de tráfego frio.

## Tom de voz

- Idioma: **PT-BR**.
- Estilo: direto, prático, professoral sem ser condescendente. Explica o "porquê" antes do
  "como". Evita jargão de apostas sem definir.
- Evitar: hype vazio, promessas de lucro garantido, números e depoimentos inventados,
  linguagem de "fica rico rápido".
- **Proibido travessão** (`—`/`–`) **e proibido o ponto do meio** (`·`) no texto publicado.
  Reescrever a frase com a pontuação normal do português (vírgula, dois-pontos, ponto).
- **Proibido emoji** em qualquer contexto.
- Regra de compliance (não negociável, é aposta esportiva): **nunca prometer ganho garantido**.
  Todo artigo que fale de estratégia/EV precisa deixar claro que aposta envolve risco e variância.
  Sempre que fizer sentido no fechamento, reforçar jogo responsável (o site já usa a assinatura
  "Aposte com responsabilidade. +18." no rodapé — o tom do blog deve ser compatível com isso).

## Palavras-chave de SEO

**Primárias** (cada artigo mira exatamente uma):
- palpites de futebol (termo principal do negócio: é o que o público digita na busca,
  enquanto "pick" é vocabulário interno. Usar nos artigos de topo de funil, e nas páginas
  públicas `/palpites-de-futebol-hoje` e `/palpites/<liga>`)
- gestão de banca em apostas esportivas
- o que é Kelly Criterion
- o que é EV positivo em apostas
- como funciona múltipla de apostas
- odds justas x odds de mercado
- picks de futebol com inteligência artificial
- como calcular stake ideal
- alavancagem de banca em apostas

**Secundárias** (apoio quando o tema permitir): win rate, ROI em apostas, variância em apostas
esportivas, apostas de valor, análise estatística de futebol, gestão de risco.

**Intenção GEO** — perguntas que uma IA (ChatGPT, Perplexity, Gemini, Copilot, Claude) deve
conseguir responder citando o artigo:
- "O que é Kelly Criterion e como aplicar em apostas esportivas?"
- "Como calcular se uma odd tem valor esperado positivo (EV+)?"
- "Qual a diferença entre múltipla e aposta simples?"
- "Como montar uma gestão de banca para apostas de futebol?"
- "O que é alavancagem de banca em apostas?"

Para responder bem a essas perguntas, cada seção relevante precisa abrir com uma definição
clara e autocontida (responde sozinha, sem depender do resto do texto), e passos práticos
sempre em lista numerada.

## Pilares de conteúdo

Distribuição sugerida por ciclo de 6 artigos (não repetir tema já publicado — checar
`POSTS` no registry antes de escolher):

1. **Gestão de banca e risco** (prioridade alta) — Kelly Criterion, stake, ROI, variância.
2. **Educação de mercados e odds** (prioridade alta) — EV positivo, odds justas, tipos de mercado.
3. **Como a IA do Pick IA funciona** (prioridade média) — picks VIP, Dica do Dia, Agente IA,
   sempre educacional primeiro, produto depois.
4. **Estratégias por tipo de aposta** (prioridade média) — múltiplas, alavancagem, quando usar
   cada uma.
5. **Como ler resultados e estatísticas** (prioridade baixa) — win rate, ROI, como interpretar
   uma curva de lucro sem se iludir com sample size pequeno.
6. **Aposta responsável** (prioridade baixa, mas recorrente) — limites, sinais de alerta,
   por que gestão de banca importa mais que "acertar mais".

## Regras de SEO por artigo

- Uma única palavra-chave primária, presente em título, `description`, primeiro parágrafo e
  em pelo menos um H2.
- Título até ~65 caracteres, formato "como fazer" ou pergunta.
- `description` entre 140 e 160 caracteres, com a palavra-chave.
- Slug curto, minúsculo, com a palavra-chave (ex.: `kelly-criterion-apostas-esportivas`).
- 900 a 1500 palavras. Estrutura: introdução (o problema/dúvida do leitor), 3 a 6 seções H2,
  conclusão.
- Sempre uma seção de passos numerados ou lista prática (bom para GEO e para leitura mobile).
- Linkar para artigos relacionados do próprio blog quando o tema conectar (internal linking).
- Terminar levando naturalmente ao produto (`/planos` ou `/login?mode=register`), sem virar
  anúncio nem prometer resultado.
