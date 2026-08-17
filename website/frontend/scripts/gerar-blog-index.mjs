/*
 * Gera public/blog-index.json a partir dos `*.meta.ts` do blog.
 *
 * POR QUE ISTO EXISTE.
 *
 * O backend monta o /llms.txt e o /blog.md, e precisa saber quais artigos
 * existem. Ele não consegue ler `src/blog/content/` em produção: a imagem
 * Docker copia só o `dist` do frontend, o código-fonte não vai junto.
 *
 * A alternativa seria manter a lista de posts escrita à mão do lado do
 * Python. Ela desatualizaria no primeiro artigo publicado, e desatualizaria
 * em silêncio · ninguém abre o llms.txt pra conferir. Gerando no build, quem
 * publica um post continua fazendo só o que o registry.ts já pede (criar o
 * `.meta.ts` e o `.tsx`) e o índice acompanha sozinho.
 *
 * Roda como `prebuild`, antes do Vite, porque escreve dentro de `public/` ·
 * é o Vite que copia esse diretório pro dist.
 *
 * SEM DEPENDÊNCIA NOVA: os `.meta.ts` são objetos literais simples, então um
 * punhado de regex resolve. Se um dia o meta virar código de verdade (import,
 * template string, condicional), o certo é trocar isto por um build TS de
 * verdade, não por regex mais esperta.
 */
import { readdir, readFile, writeFile } from 'node:fs/promises'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const raiz = join(dirname(fileURLToPath(import.meta.url)), '..')
const dirConteudo = join(raiz, 'src', 'blog', 'content')
const saida = join(raiz, 'public', 'blog-index.json')

function texto(fonte, campo) {
  const m = fonte.match(new RegExp(`${campo}:\\s*(?:'((?:[^'\\\\]|\\\\.)*)'|"((?:[^"\\\\]|\\\\.)*)")`, 's'))
  if (!m) return ''
  return (m[1] ?? m[2] ?? '').replace(/\\'/g, "'").replace(/\\"/g, '"').trim()
}

function numero(fonte, campo) {
  const m = fonte.match(new RegExp(`${campo}:\\s*(\\d+)`))
  return m ? Number(m[1]) : null
}

const arquivos = (await readdir(dirConteudo)).filter((f) => f.endsWith('.meta.ts'))
const posts = []

for (const arquivo of arquivos) {
  const fonte = await readFile(join(dirConteudo, arquivo), 'utf8')
  const slug = texto(fonte, 'slug') || arquivo.replace('.meta.ts', '')
  const title = texto(fonte, 'title')

  // Post sem título é erro de quem escreveu, e falhar o build é melhor do que
  // publicar um índice com buraco que ninguém vai notar.
  if (!title) {
    console.error(`[blog-index] ${arquivo} está sem title`)
    process.exit(1)
  }

  posts.push({
    slug,
    title,
    description: texto(fonte, 'description'),
    publishedAt: texto(fonte, 'publishedAt'),
    category: texto(fonte, 'category'),
    readingTime: numero(fonte, 'readingTime'),
  })
}

posts.sort((a, b) => (a.publishedAt < b.publishedAt ? 1 : -1))

await writeFile(
  saida,
  JSON.stringify({ gerado_em: new Date().toISOString(), posts }, null, 2),
  'utf8',
)

console.log(`[blog-index] ${posts.length} post(s) em public/blog-index.json`)
