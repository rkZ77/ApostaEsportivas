/*
 * GERA OS ÍCONES DO SITE A PARTIR DO PHOSPHOR (15/10/2026) · src/lib/icones/.
 *
 * O site desenha os ícones do Phosphor, mas NÃO leva a biblioteca pro
 * navegador: cada ícone dela carrega os seis pesos (thin, light, regular,
 * bold, fill, duotone), e com os ~117 do site o pacote principal ia de 232 KB
 * pra 551 KB · a Home é a porta de entrada de cliente novo pelo celular.
 *
 * Lê src/lib/icones/mapa.json (apelido -> nome no Phosphor) e escreve:
 *   src/lib/icones/<Apelido>.tsx   um arquivo por ícone, só com os pesos
 *                                  usados ('regular', e 'bold'/'fill' dos que
 *                                  pedem · listas abaixo)
 *   src/lib/icones/index.ts        o índice que as telas importam
 * Um arquivo por ícone é o que deixa cada um ir só no pedaço da tela que o
 * usa, como era com o lucide.
 *
 * Ícone novo: acrescente em mapa.json e rode
 *   node scripts/gerar-icones.mjs
 * (o @phosphor-icons/react fica em devDependencies só pra isto).
 */
import { readFile, writeFile, readdir, unlink } from 'node:fs/promises'
import { pathToFileURL } from 'node:url'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

const PASTA = 'src/lib/icones'
/** Desenhos que aparecem com traço grosso (strokeWidth >= 2.5 no código). */
const COM_BOLD = new Set(['Check', 'X', 'Minus', 'Clock', 'ArrowCounterClockwise', 'FirstAid'])
/** Desenhos que aparecem preenchidos (classe fill-...). */
const COM_FILL = new Set(['Star'])
/** Arquivos da pasta que NÃO são gerados. */
const MANUAIS = new Set(['criar.tsx', 'mapa.json'])

const mapa = JSON.parse(await readFile(`${PASTA}/mapa.json`, 'utf8'))

const cache = new Map()
async function desenhos(nome) {
  if (cache.has(nome)) return cache.get(nome)
  const url = pathToFileURL(`node_modules/@phosphor-icons/react/dist/defs/${nome}.es.js`).href
  const { default: pesos } = await import(url)
  const quero = ['regular', ...(COM_BOLD.has(nome) ? ['bold'] : []), ...(COM_FILL.has(nome) ? ['fill'] : [])]
  const saida = {}
  for (const peso of quero) {
    const el = pesos.get(peso)
    if (!el) throw new Error(`${nome} sem o peso ${peso}`)
    saida[peso] = renderToStaticMarkup(createElement('g', null, el)).replace(/^<g>|<\/g>$/g, '')
  }
  cache.set(nome, saida)
  return saida
}

// Limpa o que foi gerado antes (ícone que saiu do mapa não pode ficar).
for (const arq of await readdir(PASTA)) {
  if (!MANUAIS.has(arq)) await unlink(`${PASTA}/${arq}`)
}

const cabeca = '/* ARQUIVO GERADO por scripts/gerar-icones.mjs · não editar a mão.\n' +
  ' * Desenho do Phosphor (MIT, phosphoricons.com). */\n'
let bytes = 0
for (const [apelido, nome] of Object.entries(mapa)) {
  const corpo = cabeca +
    "import { criarIcone } from './criar'\n\n" +
    `export default /* @__PURE__ */ criarIcone('${apelido}', ${JSON.stringify(await desenhos(nome))})\n`
  bytes += Buffer.byteLength(corpo)
  await writeFile(`${PASTA}/${apelido}.tsx`, corpo)
}
const indice = cabeca +
  "export type { LucideIcon, IconeProps, PesoDoIcone } from './criar'\n" +
  Object.keys(mapa).map(a => `export { default as ${a} } from './${a}'`).join('\n') + '\n'
await writeFile(`${PASTA}/index.ts`, indice)
console.log(`${Object.keys(mapa).length} ícones em ${PASTA} · ${(bytes / 1024).toFixed(1)} KB no total`)
