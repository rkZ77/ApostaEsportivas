import { Helmet } from 'react-helmet-async'
import { cn } from '../lib/cn'
import Navbar from './Navbar'
import Footer from './Footer'
import BackButton from './BackButton'
import { PAGE_WIDTH, type PageWidth } from '../lib/pageWidth'
import { useRevelacao, classesRevelacao, FADE_REVELACAO_MS } from '../hooks/useRevelacao'

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
  /**
   * Mantém o `sub` visível no celular.
   *
   * O padrão de esconder existe porque na maioria das páginas o `sub` é
   * legenda, e legenda pode esperar. Em Picks ele não é: carrega o navegador
   * de dia (setas + "voltar pra Hoje"), e o site é mobile-first, então o
   * controle estava invisível justamente para a maior parte dos usuários.
   */
  subMobile?: boolean
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
  /**
   * Desliga o portão de revelação · o conteúdo aparece no primeiro quadro.
   *
   * Só para tela sem carga inicial nenhuma (Termos, Privacidade). Nas outras o
   * portão é o padrão de propósito: ver hooks/useRevelacao.
   */
  revelacao = true,
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
  revelacao?: boolean
}) {
  const revelado = useRevelacao(!revelacao)
  const fullTitle = title
    ? (title.includes('Pick IA') ? title : `${title} | Pick IA`)
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
          {/* Quebra em duas linhas antes de espremer o título.
              A fila de ações é `shrink-0`, então ela nunca cede largura · sem
              `flex-wrap` aqui, quem cedia era o título, que tem `min-w-0` e
              truncava. Numa tela de 360px com três botões (a Banca tem
              Sacar, Configurar e Zerar mês) "Minha Banca" virava "Minha B...".
              Com a quebra, as ações descem inteiras para a linha de baixo e o
              título fica legível, que é a ordem certa de prioridade. */}
          <div className={cn('mx-auto py-4 flex flex-wrap items-center justify-between gap-x-3 gap-y-2', PAGE_WIDTH[width])}>
            <div className="flex items-center gap-3 min-w-0">
              {bar.back && <BackButton to={typeof bar.back === 'string' ? bar.back : undefined} />}
              <div className="min-w-0">
                <h1 className="font-display text-base font-semibold text-ink-1 leading-tight truncate">
                  {bar.title}
                </h1>
                {bar.sub != null && (
                  <p className={`text-ink-3 text-[11px] mt-0.5 ${bar.subMobile ? '' : 'hidden sm:block'}`}>{bar.sub}</p>
                )}
              </div>
            </div>
            {/* `ml-auto` mantém as ações à direita também quando elas descem
                para a própria linha · `justify-between` do pai só alinha itens
                que dividem a MESMA linha. */}
            {bar.actions && (
              <div className="flex items-center gap-2 flex-wrap justify-end shrink-0 ml-auto">
                {bar.actions}
              </div>
            )}
          </div>
        </div>
      )}

      {/* A faixa de plano morava aqui e saiu em 21/08, a pedido do usuário.
          Ela custava uma linha inteira do topo em toda tela do app e empurrava
          para baixo justamente o conteúdo que a pessoa abriu a página para ver.
          Virou aviso de rodapé, montado uma vez em App.tsx, mais um item na
          Central de Notificações · ver components/PlanUpsellToast.tsx. */}

      {beforeMain}

      {/*
        O portão vive NO <main>, e não num <div> em volta dele.
        Sete telas passam layout por `mainClassName` · `space-y-5`, `grid
        lg:grid-cols-2`, `flex items-center` · e todas dependem de o conteúdo
        ser filho direto deste elemento. Um invólucro extra viraria o único
        filho do grid e achataria a página inteira numa coluna.
      */}
      <main
        className={cn(
          'flex-1 w-full mx-auto py-6 md:py-8',
          PAGE_WIDTH[width],
          classesRevelacao(revelado),
          mainClassName,
        )}
        style={{ transitionDuration: `${FADE_REVELACAO_MS}ms` }}
        aria-busy={!revelado}
      >
        {children}
      </main>

      {footer && <Footer />}
    </div>
  )
}
