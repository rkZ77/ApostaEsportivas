import type { ComponentType } from 'react'
import type { PostMeta } from './types'

/**
 * Descoberta automática: publicar um artigo = criar `<slug>.meta.ts` + `<slug>.tsx` em
 * ./content, nada mais. Os dois arquivos são separados (em vez de meta+componente no mesmo
 * arquivo) para que o componente vire um chunk lazy de verdade: se meta e componente vivessem
 * no mesmo módulo, o import eager de meta (necessário para listar os posts sem baixar o corpo
 * de todos) forçaria o bundler a juntar tudo em um chunk só, e a página /blog acabaria
 * baixando o texto de todo artigo publicado.
 */
const metaModules = import.meta.glob<PostMeta>('./content/*.meta.ts', {
  eager: true,
  import: 'meta',
})

const componentLoaders = import.meta.glob<ComponentType>('./content/*.tsx', {
  import: 'default',
})

function slugFromMetaPath(path: string): string {
  return path.replace('./content/', '').replace('.meta.ts', '')
}

interface PostEntry {
  meta: PostMeta
  load: () => Promise<ComponentType>
}

const entries: Record<string, PostEntry> = {}
for (const path in metaModules) {
  const slug = slugFromMetaPath(path)
  const componentPath = `./content/${slug}.tsx`
  const load = componentLoaders[componentPath] as (() => Promise<ComponentType>) | undefined
  if (!load) {
    console.warn(`[blog] ${path} não tem componente correspondente em ${componentPath}`)
    continue
  }
  entries[slug] = { meta: metaModules[path], load }
}

export const POSTS: PostMeta[] = Object.values(entries)
  .map((entry) => entry.meta)
  .sort((a, b) => (a.publishedAt < b.publishedAt ? 1 : -1))

export function getPostMeta(slug: string): PostMeta | undefined {
  return entries[slug]?.meta
}

export function getPostLoader(slug: string): (() => Promise<ComponentType>) | undefined {
  return entries[slug]?.load
}
