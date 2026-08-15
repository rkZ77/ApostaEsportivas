/*
 * Pré-comprime o build em Brotli.
 *
 * POR QUE PRÉ-COMPRIMIR, E NÃO COMPRIMIR NA HORA.
 *
 * O backend já tem GZipMiddleware, que comprime a cada requisição. Isso custa
 * CPU do processo que também responde a API, e o processo é um só. Brotli em
 * nível alto é bem mais caro que gzip: fazer isso por requisição trocaria bytes
 * por latência, que é o oposto do objetivo.
 *
 * Comprimindo no build, o custo é pago uma vez por deploy, o nível pode ser o
 * máximo (11), e servir vira só mandar outro arquivo do disco.
 *
 * SEM DEPENDÊNCIA NOVA. O Node traz Brotli no `zlib` desde a v11, então isto
 * não adiciona nada ao package.json.
 *
 * O `.gz` também sai daqui pelo mesmo motivo, para quem não aceita brotli
 * (Safari antigo, alguns proxies corporativos).
 */
import { createReadStream, createWriteStream } from 'node:fs'
import { readdir, stat } from 'node:fs/promises'
import { pipeline } from 'node:stream/promises'
import { join, extname } from 'node:path'
import { fileURLToPath } from 'node:url'
import zlib from 'node:zlib'

// fileURLToPath e nao `.pathname`: o caminho do projeto tem espaco, e o
// pathname da URL vem com %20, que o fs nao resolve.
const DIST = fileURLToPath(new URL('../dist/', import.meta.url))

// Só texto. Comprimir PNG/WOFF2 de novo gasta CPU e costuma aumentar o arquivo.
const COMPRIME = new Set(['.js', '.css', '.html', '.svg', '.json', '.txt', '.xml', '.webmanifest'])

// Abaixo disto o cabeçalho de codificação custa mais que o que se economiza,
// e o navegador ainda paga uma descompressão.
const MINIMO = 1024

async function* arquivos(dir) {
  for (const item of await readdir(dir, { withFileTypes: true })) {
    const caminho = join(dir, item.name)
    if (item.isDirectory()) yield* arquivos(caminho)
    else yield caminho
  }
}

const brotli = () => zlib.createBrotliCompress({
  params: {
    [zlib.constants.BROTLI_PARAM_QUALITY]: zlib.constants.BROTLI_MAX_QUALITY,
    [zlib.constants.BROTLI_PARAM_MODE]: zlib.constants.BROTLI_MODE_TEXT,
  },
})

let n = 0, antes = 0, depoisBr = 0

for await (const arquivo of arquivos(DIST)) {
  if (arquivo.endsWith('.br') || arquivo.endsWith('.gz')) continue
  if (!COMPRIME.has(extname(arquivo))) continue

  const { size } = await stat(arquivo)
  if (size < MINIMO) continue

  await pipeline(createReadStream(arquivo), brotli(), createWriteStream(arquivo + '.br'))
  await pipeline(
    createReadStream(arquivo),
    zlib.createGzip({ level: 9 }),
    createWriteStream(arquivo + '.gz'),
  )

  n++
  antes += size
  depoisBr += (await stat(arquivo + '.br')).size
}

const kb = (b) => (b / 1024).toFixed(1)
const corte = antes ? (100 - (depoisBr / antes) * 100).toFixed(1) : '0'
console.log(`[precomprimir] ${n} arquivos · ${kb(antes)} KB -> ${kb(depoisBr)} KB em brotli (-${corte}%)`)
