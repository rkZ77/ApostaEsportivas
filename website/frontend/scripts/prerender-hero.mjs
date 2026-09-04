/*
 * PRE-RENDERIZA O TEXTO DO HERO DENTRO DO index.html DO BUILD.
 *
 * O PROBLEMA QUE ISTO RESOLVE. O paragrafo do hero e o elemento de LCP da
 * Home. O PageSpeed de 04/09 mediu LCP de 5,7s com TTFB zero e 2.340ms de
 * "atraso de renderizacao": o servidor respondia rapido e o texto esperava o
 * React baixar, avaliar e montar. Ajuste de bundle nao resolve isso, porque o
 * piso e o proprio React existir. A unica saida e o texto nao depender dele.
 *
 * COMO. Depois do `vite build`, este script renderiza `src/home/HeroTexto.tsx`
 * com `renderToStaticMarkup` e injeta o HTML dentro do <div id="root"> do
 * dist/index.html. O navegador pinta titulo, paragrafo e botoes assim que
 * recebe HTML e CSS. Quando o bundle chega, `createRoot().render()` esvazia o
 * container e assume · nao ha hidratacao, entao markup divergente nao quebra
 * nada, no maximo repinta.
 *
 * POR QUE NAO ESCREVER O HTML A MAO NO index.html. Porque ele divergiria. Ja
 * aconteceu neste projeto: o JSON-LD com preco fixo no index.html anunciou
 * R$ 49,90 pro Google por tempo indeterminado enquanto a cobranca real era
 * R$ 39,90. Gerando a partir do componente, mudar o texto do hero continua
 * sendo mexer em um arquivo so.
 *
 * O QUE ELE NAO FAZ. Nao e SSR: nao roda por requisicao, nao consulta banco,
 * nao sabe quem esta logado. E um pedaco de HTML fixo, igual para todo mundo,
 * decidido no build. O `data-hero-estatico` no wrapper e o que o Home.tsx le
 * pra saber que nao deve reanimar a entrada (ver HERO_JA_PINTADO).
 *
 * ROTAS QUE NAO SAO A HOME. O mesmo index.html serve o SPA inteiro, entao o
 * hero estatico apareceria por um instante em /login, /planos, etc. Por isso
 * ele sai da tela sozinho quando o caminho nao e a raiz · um <style> de tres
 * linhas resolve, sem esperar JavaScript. Fora da Home o React monta por cima
 * do mesmo jeito.
 */
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { pathToFileURL } from 'node:url'
import { build } from 'esbuild'

const ALVO = 'dist/index.html'
const MARCA = '<div id="root"></div>'

/*
 * O componente e TSX e importa outros TSX, CSS e o alias do lucide · nada
 * disso o Node executa sozinho. O esbuild empacota tudo num modulo so, em
 * memoria, e o `stdin` abaixo e o ponto de entrada desse pacote.
 *
 * `.css` vira modulo vazio de proposito: o estilo ja esta no bundle do Vite, e
 * o que este script precisa e do MARKUP.
 */
const cssVazio = {
  name: 'css-vazio',
  setup(b) {
    b.onLoad({ filter: /\.css$/ }, () => ({ contents: '', loader: 'js' }))
  },
}

const entrada = `
  import { createElement } from 'react'
  import { renderToStaticMarkup } from 'react-dom/server'
  // O .js e' obrigatorio: quem resolve este import e' o Node (o esbuild deixa
  // os pacotes de fora), e ele nao adivinha extensao em subcaminho de pacote.
  // Crase nenhuma neste bloco: ele mora dentro de um template literal.
  import { StaticRouter } from 'react-router-dom/server.js'
  import HeroTexto from './src/home/HeroTexto'

  // StaticRouter porque o hero tem dois <Link>. Sem contexto de rota o
  // react-router lanca, e o build pararia aqui em vez de gerar HTML quebrado.
  export const html = renderToStaticMarkup(
        // animar: false · O HERO ESTATICO NAO ANIMA, E ISSO E' O PONTO.
    //
    // Com a entrada em fade (.entra), o texto nasce em opacity 0 e o Chrome
    // nao registra elemento invisivel como candidato a LCP · medido em 04/09:
    // o paragrafo pre-renderizado, animando, nao virava candidato, e o LCP
    // acabava caindo no paragrafo que o React recria depois (3,7s). Sem
    // animacao ele ja' esta opaco no primeiro quadro, junto com o CSS.
    createElement(StaticRouter, { location: '/' }, createElement(HeroTexto, { animar: false })),
  )
`

const { outputFiles } = await build({
  stdin: { contents: entrada, resolveDir: process.cwd(), loader: 'tsx' },
  bundle: true,
  write: false,
  format: 'esm',
  platform: 'node',
  target: 'node20',
  jsx: 'automatic',
  /*
   * So' o NOSSO codigo entra no pacote · react, react-dom e o router ficam de
   * fora e sao resolvidos pelo Node no node_modules.
   *
   * Sem isto o esbuild engolia o react-dom/server (que e' CommonJS e chama
   * `require("stream")` la dentro) e o modulo quebrava no import com
   * "Dynamic require of stream is not supported".
   */
  packages: 'external',
  plugins: [cssVazio],
  logLevel: 'warning',
})

/*
 * O pacote sai pra um arquivo temporario, e nao pra uma `data:` URL.
 *
 * Tentei a data URL primeiro: com React, react-dom/server e o router dentro,
 * o modulo passa de 1 MB, e o import de data URL desse tamanho falha no Node
 * despejando o base64 inteiro no terminal · 34 MB de saida pra um erro de uma
 * linha. Arquivo em disco importa igual e depura melhor.
 */
const temporario = 'node_modules/.cache/hero-prerender.mjs'
await mkdir('node_modules/.cache', { recursive: true })
await writeFile(temporario, outputFiles[0].text)

let modulo
try {
  modulo = await import(pathToFileURL(temporario).href)
} finally {
  await rm(temporario, { force: true })
}

const html = modulo.html
if (!html || html.length < 200) {
  throw new Error(`hero pre-renderizado veio vazio ou curto demais (${html?.length} chars)`)
}

let pagina = await readFile(ALVO, 'utf8')
if (!pagina.includes(MARCA)) {
  throw new Error(`${ALVO} nao tem mais o ${MARCA} · o hero estatico nao foi injetado`)
}

/*
 * ELE FICA FORA DO #root, E ISSO NAO E' DETALHE.
 *
 * Dentro do container, `createRoot().render()` apaga o hero no instante em que
 * o React sobe · e o React sobe ANTES da Home, que e' lazy(). Medido em 04/09:
 * o texto aparecia em 700ms, sumia em 1,1s e so' voltava em 3s, com dois
 * segundos de tela vazia no meio. Pior do que nao ter pre-renderizado nada.
 *
 * Fora do container, o React nunca o toca: o fallback das rotas e' `null` (ver
 * PageLoader no App.tsx), entao ate' a Home chegar a tela e' o hero estatico e
 * mais nada. Quem o remove e' a propria Home, no mount, quando ja' tem o seu
 * para pintar no lugar · troca no mesmo quadro, sem lacuna.
 *
 * O wrapper repete as classes de layout do hero (a secao, o grid e a coluna)
 * porque o HeroTexto e' so' a coluna esquerda: sem elas o texto nasceria na
 * largura toda e saltaria de posicao quando o React montasse · CLS pago pra
 * ganhar LCP, que e' troca ruim.
 *
 * Elas sao as MESMAS de pages/Home.tsx. Se o layout do hero mudar la, muda
 * aqui: o teste test_hero_estatico_2026_09.py segura o par.
 */
const estatico = `<div data-hero-estatico class="min-h-screen bg-surface-0 text-ink-1 overflow-x-hidden flex flex-col"><section class="relative pt-16"><div class="relative max-w-6xl mx-auto px-4 pt-14 pb-16 md:pt-20 md:pb-24"><div class="grid lg:grid-cols-2 gap-12 lg:gap-10 items-center">${html}</div></div></section></div>
    <div id="root"></div>`

/*
 * O hero estatico e' da Home, e o mesmo index.html serve o SPA inteiro. Sem
 * isto, abrir /login ou /planos mostraria o hero da Home por um segundo antes
 * de o React montar a tela certa.
 *
 * Marcar o <html> com um script sincrono no <head> resolve antes da primeira
 * pintura · CSS sozinho nao sabe o caminho da URL, e esperar JavaScript de
 * modulo seria tarde demais (e o flash aconteceria).
 */
const soNaHome = `<style>[data-fora-da-home] [data-hero-estatico]{display:none}</style>
    <script>if(location.pathname!=='/')document.documentElement.setAttribute('data-fora-da-home','')</script>
  </head>`

pagina = pagina.replace(MARCA, estatico).replace('</head>', soNaHome)
await writeFile(ALVO, pagina)

console.log(`hero estatico injetado em ${ALVO} · ${html.length} chars`)
