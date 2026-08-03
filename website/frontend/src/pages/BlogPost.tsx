import { lazy, Suspense, useMemo } from 'react'
import { useParams, Link, Navigate } from 'react-router-dom'
import { Helmet } from 'react-helmet-async'
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'
import BackButton from '../components/BackButton'
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
    <>
      <Helmet>
        <title>{meta.title} · Blog Pick IA</title>
        <meta name="description" content={meta.description} />
        <link rel="canonical" href={url} />
        <script type="application/ld+json">{JSON.stringify(jsonLd)}</script>
      </Helmet>
      <Navbar />
      <div className="min-h-screen bg-surface-0 text-ink-1">
        <div className="max-w-2xl mx-auto px-4 pt-6">
          <BackButton to="/blog" />
        </div>

        <article className="max-w-2xl mx-auto px-4 pt-4 pb-16">
          <div className="flex items-center gap-2 mb-4">
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-sm bg-green-500/10 text-green-400 border border-green-500/20">
              {meta.category}
            </span>
            <span className="text-ink-4 text-xs">{formatDate(meta.publishedAt)}</span>
            <span className="text-ink-4 text-xs">· {meta.readingTime} min de leitura</span>
          </div>

          <h1 className="text-2xl sm:text-3xl font-black mb-3 leading-tight">{meta.title}</h1>
          <p className="text-ink-2 text-sm leading-relaxed mb-6">{meta.description}</p>
          <p className="text-ink-4 text-xs mb-8">
            {meta.author.name} · {meta.author.role}
          </p>

          <Suspense fallback={<div className="text-ink-4 text-sm">Carregando artigo...</div>}>
            <ArticleComponent />
          </Suspense>

          <div className="mt-10 pt-6 border-t border-line">
            <Link to="/blog" className="text-green-400 hover:underline text-sm font-semibold">
              ← Ver todos os artigos
            </Link>
          </div>
        </article>
      </div>
      <Footer />
    </>
  )
}
