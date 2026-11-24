/*
 * Baixa os woff2 das fontes do Google e regenera src/fontes.css.
 *
 * As fontes sao servidas pelo NOSSO dominio (public/fonts) em vez de um <link>
 * pro fonts.googleapis.com. O motivo esta' no cabecalho de src/fontes.css.
 *
 * Rode a mao quando quiser subir a versao da fonte ou mexer nos pesos:
 *   node scripts/baixar-fontes.mjs
 *
 * NAO entra no prebuild de proposito: sao 3 arquivos que mudam uma vez por
 * ano, e amarrar o build a uma chamada de rede quebra o deploy no dia em que
 * o Google estiver fora do ar.
 */
import { writeFile, mkdir } from 'node:fs/promises'

/*
 * TIPOGRAFIA NOVA (24/11/2026, "tira cara de IA do site"). A Nunito,
 * arredondada, era boa parte da cara de template. Agora:
 *   Space Grotesk · titulos (h1-h3, .font-display)
 *   Geist         · texto e numeros (.font-mono vira Geist com tabular-nums)
 *   Instrument Serif italico · so' a palavra de destaque de um titulo (.font-serif)
 */
const CSS_URL =
  'https://fonts.googleapis.com/css2?family=Geist:wght@400..700&family=Space+Grotesk:wght@500..700&family=Instrument+Serif:ital@1&display=swap'

// UA de Chrome: sem isso o Google devolve o CSS antigo, com ttf no lugar de woff2.
const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

/*
 * Quais subsets guardamos.
 *
 * `latin` cobre o portugues inteiro. `latin-ext` entra so' na Nunito, que
 * escreve nome de time (Legia Warszawa, Besiktas); a Inter e' usada apenas em
 * numero (ver .font-mono no index.css), e o latin-ext dela sozinho pesava
 * 85 KB pra nada.
 */
const QUERO = {
  Geist: ['latin', 'latin-ext'],          // nome de time (Legia Warszawa, Besiktas)
  'Space Grotesk': ['latin', 'latin-ext'],
  'Instrument Serif': ['latin'],          // uma palavra por titulo, sempre em portugues
}

const cabecalho = `/*
 * FONTES SERVIDAS PELO PROPRIO DOMINIO. ARQUIVO GERADO · nao editar a mao.
 *
 * Ate' 03/09 elas vinham de um <link> pro fonts.googleapis.com no <head>. Esse
 * link e' CSS bloqueante em OUTRO dominio: antes do primeiro pixel o celular
 * pagava DNS + TLS pro googleapis, baixava o CSS, e so' entao descobria o
 * gstatic e pagava DNS + TLS de novo pra buscar o woff2. Em 4G lento foi a
 * maior fatia dos 750 ms de bloqueio de renderizacao medidos no PageSpeed.
 *
 * Agora os woff2 moram em public/fonts e vem pela mesma conexao que ja' trouxe
 * o HTML. A Geist e a Space Grotesk latin tem <link rel=preload> no
 * index.html, entao o download comeca junto com o CSS em vez de esperar por ele.
 *
 * Regerar com: node scripts/baixar-fontes.mjs
 */
`

const css = await (await fetch(CSS_URL, { headers: { 'User-Agent': UA } })).text()

await mkdir('public/fonts', { recursive: true })

const blocos = [...css.matchAll(/\/\* (\S+) \*\/\s*@font-face \{([\s\S]*?)\}/g)]
const faces = []

for (const [, subset, corpo] of blocos) {
  const familia = /font-family: '([^']+)'/.exec(corpo)[1]
  if (!QUERO[familia]?.includes(subset)) continue

  const peso = /font-weight: ([^;]+);/.exec(corpo)[1].trim()
  const estilo = (/font-style: ([^;]+);/.exec(corpo)?.[1] ?? 'normal').trim()
  const url = /url\((\S+?)\)/.exec(corpo)[1]
  const faixa = /unicode-range: ([^;]+);/.exec(corpo)[1].trim()
  const nome = `${familia.toLowerCase().replace(/\s+/g, '-')}${estilo === 'italic' ? '-italic' : ''}-${subset}.woff2`

  const bytes = Buffer.from(await (await fetch(url)).arrayBuffer())
  await writeFile(`public/fonts/${nome}`, bytes)
  console.log(`${nome}  ${(bytes.length / 1024).toFixed(1)} KB`)

  faces.push(`@font-face {
  font-family: '${familia}';
  font-style: ${estilo};
  font-weight: ${peso};
  font-display: swap;
  src: url('/fonts/${nome}') format('woff2');
  unicode-range: ${faixa};
}`)
}

await writeFile('src/fontes.css', cabecalho + faces.join('\n') + '\n')
console.log(`src/fontes.css · ${faces.length} @font-face`)
