# Superfície para agentes de IA

O que o site passou a expor para leitura automatizada, o que ficou de fora e
por quê, e os passos que só você consegue dar (painel do Cloudflare, DNS e
variáveis do Railway).

Contexto: o site é uma SPA. Quem pede o HTML recebe `<div id="root">` e um
bundle · o texto só existe depois que o navegador executa React. Buscador
grande renderiza JavaScript e se vira; agente de IA lendo por HTTP, não. Tudo
abaixo existe para fechar esse buraco sem duplicar conteúdo à mão.

## No ar depois deste deploy

| Rota | O que é |
| --- | --- |
| `/llms.txt` | Índice do site em markdown, no formato de llmstxt.org |
| `/llms-full.txt` | As páginas públicas inteiras, em um arquivo |
| `/index.md`, `/como-funciona.md`, `/planos.md`, `/resultados.md`, `/blog.md`, `/termos.md`, `/privacidade.md` | Versão markdown de cada página pública |
| `/p/{tipo}/{id}.md` | Teaser público de um pick, em markdown |
| Qualquer uma das URLs acima sem `.md`, com `Accept: text/markdown` | Mesma URL, resposta em markdown |
| `/.well-known/api-catalog` | Catálogo de APIs, formato linkset da RFC 9727 |
| `/.well-known/mcp.json` | Cartão do servidor MCP (rascunho SEP-2127) |
| `/auth.md` e `/.well-known/auth.md` | O que existe (e o que não existe) para agente agindo em nome de um usuário |
| `/mcp` | Servidor MCP, somente leitura, sem autenticação |
| Ferramentas WebMCP | Registradas no navegador via `navigator.modelContext`, quando o navegador suporta |

Regra que vale para tudo isso: **nada aparece que já não seja público**. O
mercado da dica do dia continua bloqueado para quem não tem conta, e pick de
assinante não entra em markdown nem em ferramenta de agente. O teaser em
markdown chama a mesma função da API pública, então não existe uma segunda
regra de exposição para divergir.

### O `llms.txt` não desatualiza sozinho

O preço vem de `PLANS` em `routers/payments.py`, que é a tabela que o
MercadoPago cobra. Os números de resultado vêm da mesma consulta que a página
de Resultados usa. A lista de artigos vem de `blog-index.json`, gerado no
build a partir dos `*.meta.ts` · publicar um artigo continua sendo criar os
dois arquivos de sempre, e o índice acompanha.

## Passos manuais

### 1. GA4: confirmar as variáveis no Railway (produção)

O envio de receita existe desde 16/08 e depende de duas variáveis no serviço
de produção:

- `GA_MEASUREMENT_ID` = `G-L801QMZ5ZS`
- `GA_API_SECRET` = criado em GA > Admin > Fluxos de dados > escolher o fluxo >
  Segredos da API do Measurement Protocol > Criar

Sem as duas, `send_purchase` retorna calado e nenhuma venda aparece. Confira
também que `APP_ENV` não foi mudado: fora de `production` o envio é descartado
de propósito.

Os eventos de funil (`view_item_list`, `select_item`, `begin_checkout`,
`sign_up`, `login`) passaram a sair do navegador neste deploy e não dependem
de variável nenhuma. São eles que preenchem "Jornada de compra" e a atribuição
de canal · a receita continua saindo do servidor, pelo motivo comentado em
`backend/analytics.py`.

### 2. Cloudflare: decidir sobre o bloqueio de crawler de IA

O `robots.txt` que está no ar não é o do repositório. O Cloudflare injeta um
bloco gerenciado que hoje bloqueia ClaudeBot, GPTBot, CCBot, Google-Extended,
Amazonbot, Applebot-Extended, Bytespider, CloudflareBrowserRenderingCrawler e
meta-externalagent, e declara `Content-Signal: search=yes,ai-train=no,use=reference`.

Isso não sai por commit. É Cloudflare > AI Crawl Control.

O que muda conforme a decisão:

- **Mantendo o bloqueio:** agente que age em tempo real a pedido de um usuário
  (alguém pergunta "o que é o Pick IA" no ChatGPT e ele busca na hora)
  costuma usar outro user-agent e continua lendo o `llms.txt`. O que você
  perde é aparecer em resposta construída a partir de índice pré-rastreado, e
  o treino continua barrado · que era a intenção.
- **Liberando:** ganha alcance em assistente de IA e perde a reserva de
  direito sobre treino. `ai-train=no` no Content-Signal continua valendo como
  declaração, mas depende do crawler respeitar.

Não dá para ter os dois. A recomendação, dado que o produto vive de conteúdo
diário próprio: liberar `ai-input` e manter `ai-train=no`, que é exatamente o
Content-Signal já declarado, e destravar só os agentes de leitura em tempo
real (ChatGPT-User, Claude-User, Perplexity-User) em vez dos crawlers de
treino (GPTBot, ClaudeBot, CCBot).

### 3. DNS: registro do DNS-AID

Só funciona com registro DNS, então é painel do Cloudflare > DNS > Records.

- Tipo: `TXT`
- Nome: `_agent`
- TTL: 300
- Conteúdo:

```
v=aid2;p=mcp;u=https://pickia.com.br/mcp;a=none;s=Pick IA dados publicos
```

Formato conforme a especificação AID v2 (`aid.agentcommunity.org`, também em
rascunho no IETF como `draft-mozleywilliams-dnsop-dnsaid`). Sem o campo `k`
porque não há prova de endpoint por chave Ed25519 · isso é opcional na v2 e
exigiria assinar a resposta, o que não se paga enquanto o servidor MCP for
público e sem autenticação.

## O que ficou de fora, e por quê

Cada item abaixo apareceria "verde" no scanner com um arquivo de dez linhas.
Publicar qualquer um deles hoje seria anunciar capacidade que o produto não
tem, e um agente que acredita no anúncio falha depois de já ter prometido ao
usuário que ia conseguir.

**OAuth Discovery (RFC 8414) e OAuth Protected Resource (RFC 9728).** Não
existe servidor OAuth aqui. A sessão é JWT emitido no login por e-mail e
senha, e não há emissão de credencial para terceiro. Esses dois documentos
só passam a fazer sentido no dia em que um agente puder ler conteúdo de
assinante em nome do assinante · que é uma decisão de produto, não uma tarefa
de infraestrutura. Enquanto isso, `/auth.md` diz explicitamente que o fluxo
não existe, que é a informação útil de verdade para quem está tentando.

**A2A Agent Card.** Exigiria um servidor A2A de verdade (JSON-RPC, ciclo de
vida de tarefa, streaming) para que o cartão não fosse uma promessa vazia. O
Pick IA não tem agente que executa tarefa para fora · o agente do site
conversa sobre picks dentro da assinatura. O MCP público já cobre "me dê os
dados", que é o que um agente externo realmente quer daqui.

**Skills Index.** A convenção ainda não tem formato estável, e o conteúdo
seria uma cópia do `tools/list` do MCP. Refazer isso agora é criar um segundo
lugar para desatualizar.

**Web Bot Auth.** É para quem OPERA um bot que visita sites de terceiros,
provando quem é. O Pick IA não rastreia a web: consome a API-Football com
chave. Não se aplica, e publicar um diretório de chaves sem bot que assine
requisição não significaria nada.

**Commerce (5 itens).** Depende de decidir se agente pode comprar assinatura
em nome do usuário, o que passa por MercadoPago, cobrança recorrente e
responsabilidade sobre uma compra que a pessoa não clicou. Levantamento, não
implementação, e só depois da sua decisão sobre OAuth.

## Como verificar

```bash
curl -s https://pickia.com.br/llms.txt | head -20
curl -s -H "Accept: text/markdown" https://pickia.com.br/planos | head -20
curl -sI https://pickia.com.br/como-funciona | grep -i "^link\|^vary"
curl -s https://pickia.com.br/.well-known/api-catalog
curl -s https://pickia.com.br/.well-known/mcp.json
curl -s -X POST https://pickia.com.br/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

O navegador tem que continuar recebendo HTML em todas essas URLs. Se
`curl -s https://pickia.com.br/planos` (sem cabeçalho `Accept`) devolver
markdown, algo quebrou · `*/*` não é pedido de markdown, e existe teste para
isso.

Para o GA, o critério não é o código compilar: é o evento aparecer no
DebugView com valor e item.
