import { lazy, Suspense, useMemo } from 'react'
import { useParams, Navigate } from 'react-router-dom'
import { Helmet } from 'react-helmet-async'
import { ArrowLeft } from 'lucide-react'
import PageShell from '../components/PageShell'
import { Button } from '../components/ui'
import { getPostMeta, getPostLoader } from '../blog/registry'

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

  if (!meta || !ArticleComponent) {
    return <Navigate to="/blog" replace />
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
      title={`${meta.title} · Blog Pick IA`}
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
            <span className="text-ink-4 text-xs">· {meta.readingTime} min de leitura</span>
          </div>

          <h1 className="text-2xl sm:text-3xl font-bold mb-3 leading-tight">{meta.title}</h1>
          <p className="text-ink-2 text-sm leading-relaxed mb-6">{meta.description}</p>
          <p className="text-ink-4 text-xs mb-8">
            {meta.author.name} · {meta.author.role}
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
