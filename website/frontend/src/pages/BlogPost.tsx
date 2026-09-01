import { lazy, Suspense, useMemo } from 'react'
import { useParams } from 'react-router-dom'
import { Helmet } from 'react-helmet-async'
import { ArrowLeft } from 'lucide-react'
import PageShell from '../components/PageShell'
import { Button } from '../components/ui'
import { getPostMeta, getPostLoader } from '../blog/registry'

/* Mesmo lazy do App.tsx de proposito: assim os dois compartilham um chunk
   só e o 404 não viaja dentro do bundle do blog. */
const NotFound = lazy(() => import('./NotFound'))

function formatDate(iso: string): string {
  const [year, month, day] = iso.split('-')
  return `${day}/${month}/${year}`
}

export default function BlogPost() {
  const { slug = '' } = useParams<{ slug: string }>()
  const meta = getPostMeta(slug)

  const ArticleComponent = useMemo(() => {
    const loader = getPostLoader(slug)
    if (!loader) return null
    return lazy(() => loader().then((Component) => ({ default: Component })))
  }, [slug])

  /*
   * Link de post que não existe mostra a página de erro, e não um empurrão
   * silencioso para /blog.
   *
   * O redirect fazia o leitor cair numa lista sem entender por quê: ele clicou
   * num artigo, apareceu no índice e ficou procurando o texto que nunca
   * existiu. Pior no caso mais comum · slug que mudou ou post despublicado,
   * onde o link vive fora do site (Instagram, WhatsApp) e ninguém pode
   * corrigir.
   *
   * A URL quebrada permanece na barra, de propósito: é ela que a pessoa
   * precisa ver para saber qual link avisar que está morto.
   */
  if (!meta || !ArticleComponent) {
    return (
      <Suspense fallback={null}>
        <NotFound />
      </Suspense>
    )
  }

  const url = `https://pickia.com.br/blog/${meta.slug}`
  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'BlogPosting',
    headline: meta.title,
    description: meta.description,
    datePublished: meta.publishedAt,
    author: { '@type': 'Organization', name: meta.author.name },
    publisher: { '@type': 'Organization', name: 'Pick IA', url: 'https://pickia.com.br' },
    mainEntityOfPage: { '@type': 'WebPage', '@id': url },
  }

  return (
    <PageShell
      title={`${meta.title} | Blog Pick IA`}
      description={meta.description}
      canonical={url}
      width="narrow"
      bar={{ back: '/blog', title: 'Blog' }}
    >
      <Helmet>
        <script type="application/ld+json">{JSON.stringify(jsonLd)}</script>
      </Helmet>

        <article className="pb-8">
          <div className="flex items-center gap-2 mb-4">
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-sm bg-green-500/10 text-green-400 border border-green-500/20">
              {meta.category}
            </span>
            <span className="text-ink-4 text-xs">{formatDate(meta.publishedAt)}</span>
            <span className="text-ink-4 text-xs">, {meta.readingTime} min de leitura</span>
          </div>

          <h1 className="text-2xl sm:text-3xl font-bold mb-3 leading-tight">{meta.title}</h1>
          <p className="text-ink-2 text-sm leading-relaxed mb-6">{meta.description}</p>
          <p className="text-ink-4 text-xs mb-8">
            {meta.author.name}, {meta.author.role}
          </p>

          <Suspense fallback={<div className="text-ink-4 text-sm">Carregando artigo...</div>}>
            <ArticleComponent />
          </Suspense>

          <div className="mt-10 pt-6 border-t border-line">
            <Button to="/blog" variant="link" size="sm" Icon={ArrowLeft} className="px-0">
              Ver todos os artigos
            </Button>
          </div>
        </article>
    </PageShell>
  )
}
