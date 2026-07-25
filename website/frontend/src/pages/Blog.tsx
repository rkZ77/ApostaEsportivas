import { Link } from 'react-router-dom'
import { Helmet } from 'react-helmet-async'
import { BookOpen } from 'lucide-react'
import Navbar from '../components/Navbar'
import Footer from '../components/Footer'
import { POSTS } from '../blog/registry'

function formatDate(iso: string): string {
  const [year, month, day] = iso.split('-')
  return `${day}/${month}/${year}`
}

export default function Blog() {
  return (
    <>
      <Helmet>
        <title>Blog Pick IA · Gestão de banca e estratégia em apostas esportivas</title>
        <meta
          name="description"
          content="Artigos sobre gestão de banca, Kelly Criterion, EV positivo e estratégia para apostas esportivas de futebol, direto da equipe do Pick IA."
        />
        <link rel="canonical" href="https://pickia.com.br/blog" />
      </Helmet>
      <Navbar />
      <div className="min-h-screen bg-black text-white">
        <div className="max-w-3xl mx-auto px-4 pt-10 pb-8 text-center">
          <div className="inline-flex items-center gap-2 bg-green-500/10 border border-green-500/20 rounded-sm px-4 py-1.5 mb-6">
            <BookOpen className="w-3.5 h-3.5 text-green-400" />
            <span className="text-green-400 text-xs font-bold">Blog Pick IA</span>
          </div>
          <h1 className="text-3xl sm:text-4xl font-black mb-4 leading-tight">
            Gestão de banca e estratégia<br />
            <span className="text-green-500">para apostas esportivas</span>
          </h1>
          <p className="text-zinc-400 text-sm max-w-lg mx-auto leading-relaxed">
            Conteúdo prático sobre Kelly Criterion, valor esperado, odds e como interpretar
            resultados, sem promessa de ganho garantido.
          </p>
        </div>

        <div className="max-w-3xl mx-auto px-4 pb-16">
          {POSTS.length === 0 ? (
            <p className="text-zinc-500 text-sm text-center py-12">Nenhum artigo publicado ainda.</p>
          ) : (
            <div className="space-y-4">
              {POSTS.map((post) => (
                <Link
                  key={post.slug}
                  to={`/blog/${post.slug}`}
                  className="block border border-zinc-800 bg-zinc-900/40 hover:border-green-500/40 hover:bg-zinc-900 rounded-lg p-5 transition-colors"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-sm bg-green-500/10 text-green-400 border border-green-500/20">
                      {post.category}
                    </span>
                    <span className="text-zinc-600 text-xs">{formatDate(post.publishedAt)}</span>
                    <span className="text-zinc-600 text-xs">· {post.readingTime} min de leitura</span>
                  </div>
                  <h2 className="text-white font-black text-lg mb-1.5 leading-snug">{post.title}</h2>
                  <p className="text-zinc-400 text-sm leading-relaxed">{post.description}</p>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>
      <Footer />
    </>
  )
}
