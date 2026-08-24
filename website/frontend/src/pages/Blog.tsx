import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { BookOpen } from 'lucide-react'
import PageShell from '../components/PageShell'
import EmptyState from '../components/ui/EmptyState'
import { POSTS } from '../blog/registry'
import { fadeInUp, staggerContainer } from '../lib/motion'

function formatDate(iso: string): string {
  const [year, month, day] = iso.split('-')
  return `${day}/${month}/${year}`
}

export default function Blog() {
  return (
    <PageShell
      title="Blog Pick IA · Gestão de banca e estratégia em apostas esportivas"
      description="Artigos sobre gestão de banca, Kelly Criterion, EV positivo e estratégia para apostas esportivas de futebol, direto da equipe do Pick IA."
      canonical="https://pickia.com.br/blog"
      width="prose"
    >
        <div className="pb-8 text-center">
          <div className="inline-flex items-center gap-2 bg-green-500/10 border border-green-500/20 rounded-sm px-4 py-1.5 mb-6">
            <BookOpen className="w-3.5 h-3.5 text-green-400" />
            <span className="text-green-400 text-xs font-bold">Blog Pick IA</span>
          </div>
          <h1 className="text-3xl sm:text-4xl font-bold mb-4 leading-tight">
            Gestão de banca e estratégia<br />
            <span className="text-accent-ink">para apostas esportivas</span>
          </h1>
          <p className="text-ink-2 text-sm max-w-lg mx-auto leading-relaxed">
            Conteúdo prático sobre Kelly Criterion, valor esperado, odds e como interpretar
            resultados, sem promessa de ganho garantido.
          </p>
        </div>

        <div className="pb-8">
          {POSTS.length === 0 ? (
            <EmptyState
              Icon={BookOpen}
              title="Nenhum artigo publicado ainda"
              description="Estamos escrevendo. Enquanto isso, dá pra conferir o histórico auditável dos picks."
              action={{ children: 'Ver resultados', to: '/resultados', variant: 'ghost' }}
            />
          ) : (
            <motion.div variants={staggerContainer} initial="hidden" animate="visible" className="space-y-4">
              {POSTS.map((post) => (
                <motion.div key={post.slug} variants={fadeInUp} whileHover={{ y: -2 }}>
                  <Link
                    to={`/blog/${post.slug}`}
                    className="block border border-line bg-surface-1/40 hover:border-green-500/40 hover:bg-surface-1 rounded-lg p-5 transition-colors"
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded-sm bg-green-500/10 text-green-400 border border-green-500/20">
                        {post.category}
                      </span>
                      <span className="text-ink-4 text-xs">{formatDate(post.publishedAt)}</span>
                      <span className="text-ink-4 text-xs">· {post.readingTime} min de leitura</span>
                    </div>
                    <h2 className="text-ink-1 font-bold text-lg mb-1.5 leading-snug">{post.title}</h2>
                    <p className="text-ink-2 text-sm leading-relaxed">{post.description}</p>
                  </Link>
                </motion.div>
              ))}
            </motion.div>
          )}
        </div>
    </PageShell>
  )
}
