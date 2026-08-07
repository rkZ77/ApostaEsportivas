import { Helmet } from 'react-helmet-async'
import { cn } from '../lib/cn'
import Navbar from './Navbar'
import Footer from './Footer'
import BackButton from './BackButton'
import { PAGE_WIDTH, type PageWidth } from '../lib/pageWidth'

/*
 * Casca de página.
 *
 * Antes cada tela montava a sua: das 23 páginas, 5 usavam .shell, o resto
 * escolhia entre max-w-7xl, 6xl, 5xl, 3xl e 2xl a esmo; o Footer aparecia em 8
 * delas; e só 8 declaravam <Helmet>, então metade do site compartilhava o
 * mesmo título de aba e a mesma description no resultado de busca.
 *
 * A escala de largura e o porquê de cada degrau vivem em lib/pageWidth.
 */

export interface PageBar {
  title: React.ReactNode
  /** Linha de apoio. Some abaixo de sm, onde o espaço é do título. */
  sub?: React.ReactNode
  /** Botões à direita. */
  actions?: React.ReactNode
  /** true volta uma no histórico; string navega para a rota. */
  back?: boolean | string
}

export default function PageShell({
  children,
  title,
  description,
  canonical,
  /** Fora do índice de busca. Todo conteúdo atrás de login usa isto. */
  noindex,
  width = 'default',
  /** Navbar do app. Desligar em página que monta a própria (Home, Login). */
  nav = true,
  footer = true,
  bar,
  /** Renderizado entre a barra e o conteúdo, na largura toda (abas, banner). */
  beforeMain,
  className,
  mainClassName,
}: {
  children: React.ReactNode
  /** Vira "<title> · Pick IA". Passar já com o sufixo desliga o automático. */
  title?: string
  description?: string
  canonical?: string
  noindex?: boolean
  width?: PageWidth
  /**
   * true usa a Navbar do app, false não põe nenhuma, e um nó monta a sua.
   * O nó existe para página pública que também abre logada (Resultados, pick
   * compartilhado): deslogado, a Navbar do app só oferece links privados que
   * jogam o visitante direto no login.
   */
  nav?: boolean | React.ReactNode
  footer?: boolean
  bar?: PageBar
  beforeMain?: React.ReactNode
  className?: string
  mainClassName?: string
}) {
  const fullTitle = title
    ? (title.includes('Pick IA') ? title : `${title} · Pick IA`)
    : undefined

  return (
    <div className={cn('min-h-screen bg-surface-0 text-ink-1 flex flex-col', className)}>
      {(fullTitle || description || noindex || canonical) && (
        <Helmet>
          {fullTitle && <title>{fullTitle}</title>}
          {description && <meta name="description" content={description} />}
          {canonical && <link rel="canonical" href={canonical} />}
          {/* Tela de usuário não deve indexar: o robô só veria a casca vazia,
              e essas URLs competiam com as páginas públicas na busca. */}
          {noindex && <meta name="robots" content="noindex, nofollow" />}
        </Helmet>
      )}

      {nav === true ? <Navbar width={width} /> : nav || null}

      {bar && (
        <div className="border-b border-line">
          <div className={cn('mx-auto py-4 flex items-center justify-between gap-3', PAGE_WIDTH[width])}>
            <div className="flex items-center gap-3 min-w-0">
              {bar.back && <BackButton to={typeof bar.back === 'string' ? bar.back : undefined} />}
              <div className="min-w-0">
                <h1 className="font-display text-base font-semibold text-ink-1 leading-tight truncate">
                  {bar.title}
                </h1>
                {bar.sub != null && (
                  <p className="text-ink-3 text-[11px] mt-0.5 hidden sm:block">{bar.sub}</p>
                )}
              </div>
            </div>
            {bar.actions && (
              <div className="flex items-center gap-2 flex-wrap justify-end shrink-0">
                {bar.actions}
              </div>
            )}
          </div>
        </div>
      )}

      {beforeMain}

      <main className={cn('flex-1 w-full mx-auto py-6 md:py-8', PAGE_WIDTH[width], mainClassName)}>
        {children}
      </main>

      {footer && <Footer />}
    </div>
  )
}
