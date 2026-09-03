import { useCallback, useEffect, useMemo, useState } from 'react'
import { Helmet } from 'react-helmet-async'
import { motion } from 'framer-motion'
import { ArrowRight, Check, X as XIcon } from 'lucide-react'

import api from '../services/api'
import { rotuloDoMercado } from '../utils/marketTranslate'
import SiteHeader from '../components/SiteHeader'
import Footer from '../components/Footer'
import {
  Badge, Button, LiveDot, Panel, PanelHead, PickTypeBadge, ResultBadge,
  SectionHead, Spinner,
} from '../components/ui'
import { TeamLogo } from '../components/TeamLogo'
import PipelineProfitChart from '../components/PipelineProfitChart'
import { usePlans, fmtPlanPrice, type Plan } from '../hooks/usePlans'
import { fadeInUp, staggerContainer } from '../lib/motion'
import { MODULOS_FREE, MODULOS_VIP } from '../lib/oferta'
import { fmtUnits } from '../utils/format'
import { PICK_TYPE_LABEL } from '../utils/resultStyle'
import { useAuth } from '../context/AuthContext'
import { encerrarBarraInicial } from '../lib/barraInicial'

import FreePickHero from '../home/FreePickHero'
import StatsBand, { type PublicSummary } from '../home/StatsBand'
import HowItWorks from '../home/HowItWorks'
import Products from '../home/Products'
import FinalCTA from '../home/FinalCTA'
import Leagues from '../home/Leagues'
import NextGames from '../home/NextGames'

/*
 * Home.
 *
 * Antes se chamava Landing e era uma página de vendas com pedaços de produto
 * espalhados. A ordem agora é: promessa, prova, método, produto, prova social,
 * preço, chamada. Cada bloco de "prova" lê de endpoint público, então nada aqui
 * é número escrito à mão.
 *
 * O cabeçalho é o SiteHeader (transparente sobre o hero, com blur ao rolar),
 * não a Navbar do app: visitante deslogado não tem o que fazer com links de
 * /banca e /meus-picks.
 */

interface RecentTip {
  match_date: string
  /** Horário do jogo · só existe enquanto a partida está em `fixtures`. */
  match_datetime?: string | null
  home_team_name: string
  away_team_name?: string
  home_team_id?: number
  away_team_id?: number
  market: string
  line?: string
  odd: number
  result: string
  profit: number
  source: string
}

interface PublicData {
  /** Legenda do plano de stake · montada em backend/stake_plan.py. */
  stake_label?: string
  summary: PublicSummary
  recent: RecentTip[]
  recent_total?: number
  by_league?: Array<{ league_id: number | null; league_name: string }>
}

/* ── Últimos resultados ─────────────────────────────────────────────────── */

const PAGE_SIZE = 10

function RecentResults({ summary }: { summary: PublicSummary | null }) {
  const [page, setPage]       = useState(0)
  const [produto, setProduto] = useState<string | null>(null)
  const [recent, setRecent]   = useState<RecentTip[]>([])
  const [total, setTotal]     = useState(0)
  const [pageLoading, setPageLoading] = useState(true)

  /* Produtos observados na janela atual (para os chips de filtro). */
  const produtos = useMemo(() => {
    const vistos: string[] = []
    for (const t of recent) if (!vistos.includes(t.source)) vistos.push(t.source)
    return vistos
  }, [recent])

  /* Toda vez que página ou filtro de produto mudam, busca no backend. */
  useEffect(() => {
    setPageLoading(true)
    const params: Record<string, unknown> = {
      recent_limit:  PAGE_SIZE,
      recent_offset: page * PAGE_SIZE,
      slim: 1,
    }
    if (produto) params.source = produto
    api.get('/public/results', { params })
      .then(r => {
        setRecent(r.data?.recent ?? [])
        setTotal(r.data?.recent_total ?? 0)
      })
      .catch(() => { setRecent([]); setTotal(0) })
      .finally(() => setPageLoading(false))
  }, [page, produto])

  /* Ao trocar filtro de produto, volta pra página 0. */
  const handleProduto = (p: string | null) => {
    setProduto(p)
    setPage(0)
  }

  const totalPages = Math.ceil(total / PAGE_SIZE)

  const resumo = summary

  /*
   * Curva de lucro por produto · a prova mais forte que esta seção tem.
   */
  const [curva, setCurva] = useState<Array<{ match_date: string; source: string; profit: number }>>([])
  useEffect(() => {
    api.get('/public/profit-curve', { params: { days: 180 } })
      .then(r => setCurva(r.data ?? []))
      .catch(() => setCurva([]))
  }, [])

  return (
    <section id="resultados" className="section section-alt">
      <div className="shell">
        <SectionHead
          title="Resultados reais, verificáveis"
          sub="Todo pick publicado fica registrado. Qualquer pessoa pode conferir, sem conta."
        />

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '0px 0px -80px 0px' }}
          transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
        >
          {curva.length > 0 && (
            <Panel className="mb-4">
              <PanelHead
                label="Lucro acumulado por produto"
                meta="em unidades, últimos 180 dias"
              />
              <div className="p-5">
                <PipelineProfitChart data={curva} height={220} />
              </div>
            </Panel>
          )}

          <Panel>
            <PanelHead
              label="Últimas finalizadas"
              meta={`${total > 0 ? `${total} picks` : ''}${produto ? `, só ${PICK_TYPE_LABEL[produto] ?? produto}` : ', ordenados por data e hora da partida'}`}
            />

            {/* Chips de filtro por produto — sempre visíveis quando há mais de um tipo */}
            <div className="flex flex-wrap gap-1.5 px-4 pt-3">
              {[null, ...produtos].map(chave => {
                const ativo = produto === chave
                return (
                  <button
                    key={chave ?? 'todos'}
                    onClick={() => handleProduto(chave)}
                    className={`text-[11px] font-semibold px-2.5 py-1.5 min-h-[32px] rounded-md border transition-colors ${
                      ativo
                        ? 'border-accent/50 bg-accent/10 text-accent-ink'
                        : 'border-line text-ink-3 hover:text-ink-2 hover:border-line-strong'}`}
                  >
                    {chave === null ? 'Todos' : (PICK_TYPE_LABEL[chave] ?? chave)}
                  </button>
                )
              })}
            </div>

            {pageLoading ? (
              <div className="flex justify-center py-10"><Spinner size="md" /></div>
            ) : recent.length === 0 ? (
              <p className="text-center text-ink-4 text-sm py-8">Nenhum resultado ainda.</p>
            ) : (
              <div className="divide-y divide-line/50">
                {recent.map((tip, i) => (
                  <div key={i} className="flex items-center gap-2 px-4 py-3">
                    {/* Data e hora da partida: ordenados cronologicamente, mais
                        recente no topo. Hora vem de `fixtures` (efêmera), então
                        picks antigos mostram só a data. */}
                    <span className="font-mono text-[10px] text-ink-4 tabular-nums shrink-0 w-10 leading-tight">
                      <span className="block">
                        {new Date(tip.match_date + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })}
                      </span>
                      {tip.match_datetime && (
                        <span className="block text-ink-3">{tip.match_datetime.slice(11, 16)}</span>
                      )}
                    </span>

                    <PickTypeBadge type={tip.source} short />

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <TeamLogo id={tip.home_team_id} name={tip.home_team_name} size={16} />
                        <span className="text-xs text-ink-1 font-medium truncate">{tip.home_team_name}</span>
                        {tip.away_team_name && tip.away_team_name !== '--' && (
                          <>
                            <span className="text-ink-4 text-[10px] shrink-0">x</span>
                            <TeamLogo id={tip.away_team_id} name={tip.away_team_name} size={16} />
                            <span className="text-xs text-ink-1 font-medium truncate">{tip.away_team_name}</span>
                          </>
                        )}
                      </div>
                      <p className="text-[10px] text-ink-3 truncate mt-0.5">
                        {rotuloDoMercado(tip.market, tip.line)}
                      </p>
                    </div>

                    <span className="font-mono text-[11px] font-bold text-ink-2 tabular-nums shrink-0">
                      {Number(tip.odd).toFixed(2)}
                    </span>
                    <ResultBadge result={tip.result} />
                  </div>
                ))}
              </div>
            )}

            {/* Paginação */}
            <div className="px-4 py-3 border-t border-line flex items-center justify-between gap-2 flex-wrap">
              <button
                onClick={() => setPage(p => Math.max(0, p - 1))}
                disabled={page === 0 || pageLoading}
                className="text-xs font-semibold px-3 py-1.5 rounded-md border border-line text-ink-3 hover:text-ink-2 hover:border-line-strong disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                ← Anterior
              </button>
              <span className="text-[11px] text-ink-4 tabular-nums">
                {totalPages > 0 ? `Pág. ${page + 1} de ${totalPages}` : ''}
              </span>
              <button
                onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1 || pageLoading}
                className="text-xs font-semibold px-3 py-1.5 rounded-md border border-line text-ink-3 hover:text-ink-2 hover:border-line-strong disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                Próxima →
              </button>
            </div>

            <div className="px-5 pb-4 flex items-center justify-center gap-4 flex-wrap">
              <Button to="/resultados" variant="link" size="sm">Ver histórico completo</Button>
              <span className="text-ink-4">,</span>
              <Button to="/login?mode=register" variant="link" size="sm" className="text-accent-ink hover:text-accent-hover">
                Criar conta grátis
              </Button>
            </div>
          </Panel>

          {/* Fechamento da seção de prova. */}
          {resumo && resumo.total > 0 && (
            <div className="mt-8 text-center max-w-xl mx-auto">
              <p className="text-ink-1 text-sm font-semibold mb-1.5">
                São {resumo.total} picks publicados antes da bola rolar, com{' '}
                {resumo.greens} greens e {fmtUnits(Number(resumo.profit ?? 0), 1)} de lucro.
              </p>
              <p className="text-ink-3 text-xs leading-relaxed mb-4">
                Cada um deles fica registrado com data, mercado e odd, e o resultado é
                conferido contra a estatística oficial da partida. Você não precisa
                acreditar em nós: dá para abrir o histórico e conferir pick por pick,
                sem criar conta.
              </p>
              <Button to="/login?mode=register" size="lg" IconRight={ArrowRight}>
                Testar o VIP grátis por 2 dias
              </Button>
            </div>
          )}
        </motion.div>
      </div>
    </section>
  )
}

/* ── Planos ─────────────────────────────────────────────────────────────── */

/*
 * A COMPARAÇÃO SAI DE lib/oferta, e não de uma lista escrita aqui.
 *
 * Esta era a TERCEIRA cópia do catálogo: a vitrine e o checkout já foram
 * unificados, e a tabela de planos da Home continuou à mão. Ela já estava
 * defasada · anunciava oito itens bloqueados no Free e nenhum deles era o Pick
 * Boost nem a estatística de jogador, os dois módulos mais recentes. Quem
 * compara plano numa tabela que esquece dois produtos decide com menos do que
 * existe.
 *
 * O Free lista o que ele tem E o que não tem, porque é assim que uma coluna de
 * comparação funciona: sem os itens em cinza, a pessoa não sabe o que está
 * deixando na mesa.
 */
const FREE_ITEMS: Array<[boolean, string]> = [
  ...MODULOS_FREE.map(m => [true, m.titulo] as [boolean, string]),
  ...MODULOS_VIP.map(m => [false, m.titulo] as [boolean, string]),
]

const TRIAL_ITEMS = [
  'Experimente tudo por 2 dias, sem pagar nada',
  'Vence sozinho, sem cobrança automática',
]

/* VIP é tudo: o que já vem no Free mais o que a assinatura abre. */
const VIP_ITEMS = [...MODULOS_FREE, ...MODULOS_VIP].map(m => m.titulo)

function Plans({ monthly }: { monthly: Plan }) {
  return (
    <section id="planos" className="section section-alt">
      <div className="shell">
        <SectionHead
          title="Comece de graça, assine se gostar"
          sub="2 dias com acesso VIP completo, sem precisar de cartão."
        />

        <motion.div
          variants={staggerContainer}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '0px 0px -80px 0px' }}
          className="grid md:grid-cols-3 gap-4 items-start"
        >
          {/* Free */}
          <motion.div variants={fadeInUp} className="bg-surface-0 border border-line rounded-lg p-6">
            <Badge tone="neutral">Free</Badge>
            <p className="font-mono text-3xl font-bold text-ink-1 mt-3 mb-0.5">R$ 0</p>
            <p className="text-ink-3 text-xs mb-6">Para sempre, sem cadastro de cartão</p>
            <ul className="space-y-2.5 mb-7">
              {FREE_ITEMS.map(([ok, t]) => (
                <li key={t} className="flex items-start gap-2.5">
                  {ok
                    ? <Check className="w-4 h-4 text-accent-ink shrink-0 mt-0.5" />
                    : <XIcon className="w-4 h-4 text-ink-4 shrink-0 mt-0.5" />}
                  <span className={`text-sm leading-snug ${ok ? 'text-ink-2' : 'text-ink-4'}`}>{t}</span>
                </li>
              ))}
            </ul>
            <Button to="/login?mode=register" variant="ghost" block>Criar conta grátis</Button>
          </motion.div>

          {/* VIP · destaque principal */}
          <motion.div variants={fadeInUp} className="relative bg-surface-0 border border-yellow-400/50 rounded-lg p-6 overflow-hidden">
            <div aria-hidden="true" className="absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-transparent via-yellow-400/80 to-transparent" />
            <div className="flex items-center justify-between gap-2 mb-3">
              <Badge tone="yellow">VIP</Badge>
              <Badge tone="yellow">Mais popular</Badge>
            </div>
            <p className="font-mono text-3xl font-bold text-ink-1 mb-0.5">
              {fmtPlanPrice(monthly.price)}<span className="text-base font-semibold text-ink-3">/mês</span>
            </p>
            <p className="text-ink-3 text-xs mb-6">
              Menos de {fmtPlanPrice(monthly.price / 30)} por dia. Pagamento único, sem renovação automática.
            </p>
            <ul className="space-y-2.5 mb-7">
              {VIP_ITEMS.map(t => (
                <li key={t} className="flex items-start gap-2.5">
                  <Check className="w-4 h-4 text-yellow-400 shrink-0 mt-0.5" />
                  <span className="text-sm text-ink-2 leading-snug">{t}</span>
                </li>
              ))}
            </ul>
            <Button to="/planos" variant="vip" block>Ver planos VIP</Button>
          </motion.div>

          {/* Teste grátis · gateway para o VIP */}
          <motion.div variants={fadeInUp} className="relative bg-surface-0 border border-accent/40 rounded-lg p-6 overflow-hidden">
            <div aria-hidden="true" className="absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-transparent via-accent/60 to-transparent" />
            <Badge tone="green">Teste gratuito</Badge>
            <p className="font-mono text-3xl font-bold text-ink-1 mt-3 mb-0.5">R$ 0</p>
            <p className="text-ink-2 text-xs mb-5">Acesso VIP completo por 2 dias</p>
            {/* O trial dá acesso ao mesmo conjunto do VIP -- por isso não lista
                item por item: repete o VIP ao lado e confunde quem compara. */}
            <div className="rounded-md bg-surface-1 border border-line px-4 py-3.5 mb-5 space-y-2">
              {TRIAL_ITEMS.map(t => (
                <p key={t} className="text-sm text-ink-2 leading-snug flex items-start gap-2">
                  <Check className="w-4 h-4 text-accent-ink shrink-0 mt-0.5" />
                  {t}
                </p>
              ))}
              <p className="text-xs text-ink-3 pt-1 border-t border-line mt-1">
                Tudo que está incluso no VIP, por 2 dias.
              </p>
            </div>
            <Button to="/login?mode=register" block>Ativar teste gratuito</Button>
          </motion.div>
        </motion.div>
      </div>
    </section>
  )
}

/* ── CTA fixo no rodapé, só mobile ──────────────────────────────────────── */

function StickyMobileCTA({ onDismiss, titulo, sub, acao, destino }: {
  onDismiss: () => void; titulo: string; sub: string; acao: string; destino: string
}) {
  return (
    <div className="fixed bottom-0 inset-x-0 z-40 sm:hidden bg-surface-0/95 backdrop-blur-md border-t border-line px-4 py-3 flex items-center gap-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
      <div className="flex-1 min-w-0">
        <p className="text-ink-1 text-xs font-bold leading-none">{titulo}</p>
        <p className="text-accent-ink text-[10px] font-semibold mt-1">{sub}</p>
      </div>
      <Button to={destino} size="sm">{acao}</Button>
      <button
        onClick={onDismiss}
        className="text-ink-4 hover:text-ink-2 p-2 shrink-0"
        aria-label="Fechar chamada"
      >
        <XIcon className="w-4 h-4" />
      </button>
    </div>
  )
}

/* ── Página ─────────────────────────────────────────────────────────────── */

/*
 * O H1 carrega a palavra-chave do negócio, e não a descrição do produto.
 *
 * A versão anterior era "Inteligência artificial que encontra valor antes do
 * mercado" -- verdadeira, e sem uma única palavra que alguém digita no Google.
 * Quem procura este produto escreve "palpites de futebol", nunca "pick". O
 * termo do mercado fica no nome da marca e no resto da página; o título da
 * home fala a língua da busca.
 */
const HEADLINE = ['Palpites de futebol', 'com valor calculado,', 'não com achismo.']

export default function Home() {
  const [data, setData] = useState<PublicData | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [ctaDismissed, setCtaDismissed] = useState(false)

  /*
   * A faixa fixa do rodapé mobile vendia "Criar conta" pra todo mundo, VIP
   * pagante incluído · a Home nem lia o contexto de autenticação. Quem já
   * assina não tem conta pra criar nem trial pra testar, e a faixa só ocupava
   * a barra inferior do celular dele.
   *
   * Free e trial continuam vendo uma chamada, mas a que faz sentido pra eles:
   * o caminho é o plano, não o cadastro que já existe.
   */
  const { user } = useAuth()
  const ctaFaixa = !user
    ? { titulo: 'Testar o VIP por 2 dias', sub: 'Grátis', acao: 'Criar conta', destino: '/login?mode=register' }
    : user.plan === 'free' || user.plan === 'trial'
    ? { titulo: 'Desbloqueie os picks VIP', sub: 'Todos os produtos da IA', acao: 'Ver planos', destino: '/planos' }
    : null
  const { plans, monthly } = usePlans()

  /*
   * REVELAÇÃO COLETIVA DO TOPO.
   *
   * São três requests independentes acima da dobra · a dica do dia, a fila de
   * jogos e os indicadores. Cada bloco revelava o seu assim que a SUA resposta
   * chegava, então a Home se montava em três tempos, na ordem em que o servidor
   * respondesse, e dois desses blocos somem quando não têm dado
   * (FreePickHero, NextGames): não era só piscar em sequência, era a altura da
   * página mudando embaixo do dedo de quem está no celular.
   *
   * Os três pedidos continuam saindo juntos, no mesmo instante · isto NÃO é uma
   * fila, ninguém espera ninguém para pedir. O que espera é só a troca do
   * esqueleto pelo conteúdo, que acontece de uma vez para os três.
   *
   * Abaixo da dobra fica como estava, preenchendo conforme chega: quem rolou
   * até lá não vê o rearranjo, e segurar a página inteira significaria esperar
   * a chamada mais lenta para mostrar qualquer coisa.
   */
  const [prontos, setProntos] = useState(0)
  const marcarPronto = useCallback(() => setProntos(n => n + 1), [])
  const topoPronto = loaded && prontos >= 2

  /*
   * A Home não usa o portão de revelação das telas do app, e é de propósito:
   * o hero é estático e pinta no primeiro quadro, então segurá-lo esperando
   * dado seria trocar a tela mais rápida do site por uma espera. O que ela tem
   * é a revelação coletiva do topo, logo acima.
   *
   * A barra verde do index.html, essa, fecha aqui · o topo montado com
   * conteúdo é o mesmo marco que o portão usa nas outras telas.
   */
  useEffect(() => { if (topoPronto) encerrarBarraInicial() }, [topoPronto])

  // Esta chamada alimenta SÓ a faixa de indicadores. A lista de resultados tem
  // a sua, paginada, no efeito lá de cima (recent_limit: PAGE_SIZE).
  //
  // recent_limit=1 porque este bloco não lê `recent`, e a rota não aceita zero.
  // Já foi 50: o backend roda uma sub-query por tipo de pick (seis) buscando 50
  // linhas cada, ordenava as 300 e devolvia todas, para a Home jogar 40 fora
  // num `.slice(0, 10)` que hoje nem existe mais.
  //
  // slim=1 pelo mesmo motivo, um nível acima: a resposta trazia sete blocos e
  // esta tela lê três. `by_day` era o pior · uma linha por dia desde o
  // lançamento, baixada inteira para não ser usada em lugar nenhum. Com slim a
  // rota faz duas consultas em vez de sete (ver public.py:/results).
  useEffect(() => {
    /* Só summary e stake_label · RecentResults faz sua própria chamada paginada. */
    api.get('/public/results', { params: { recent_limit: 1, slim: 1 } })
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoaded(true))
  }, [])

  /*
   * Oferta do schema.org montada a partir do catálogo real.
   *
   * Estava fixa no index.html e ficou anunciando R$ 49,90 pro Google por tempo
   * indeterminado, com a cobrança em R$ 39,90. Gerando aqui, um reajuste no
   * backend chega no dado estruturado sozinho.
   */
  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'SoftwareApplication',
    name: 'Pick IA',
    applicationCategory: 'SportsApplication',
    operatingSystem: 'Web, iOS, Android',
    url: 'https://pickia.com.br',
    description: 'Plataforma de análise esportiva com inteligência artificial. Estatística real de futebol, probabilidade calculada e picks com valor esperado positivo.',
    offers: [
      { '@type': 'Offer', name: 'Plano Free', price: '0', priceCurrency: 'BRL' },
      ...plans.map(p => ({
        '@type': 'Offer',
        name: `Plano VIP ${p.label}`,
        price: p.price.toFixed(2),
        priceCurrency: 'BRL',
        billingIncrement: p.iso_period,
      })),
    ],
  }

  return (
    <div className={`min-h-screen bg-surface-0 text-ink-1 overflow-x-hidden flex flex-col ${ctaDismissed || !ctaFaixa ? '' : 'pb-20 sm:pb-0'}`}>
      <Helmet>
        <title>Palpites de Futebol Hoje com IA | Pick IA</title>
        <meta
          name="description"
          content="Palpites de futebol gerados por inteligência artificial. Estatística real de cada jogo, probabilidade calculada e apenas entradas com valor esperado positivo. Histórico público e auditável. Teste grátis por 2 dias."
        />
        <link rel="canonical" href="https://pickia.com.br/" />
        <script type="application/ld+json">{JSON.stringify(jsonLd)}</script>
      </Helmet>

      <SiteHeader />

      {/* ── Hero ── */}
      <section className="relative pt-16">
        <div
          aria-hidden="true"
          className="absolute inset-0 bg-data-grid bg-[length:32px_32px] [mask-image:radial-gradient(ellipse_65%_55%_at_50%_0%,black,transparent)]"
        />
        {/* Brilho do hero em radial-gradient, não em `blur-[120px]`.
            Desfoque de 120px sobre uma área de 560x320 obriga o navegador a
            criar uma camada e refiltrá-la; no Safari do iPhone é o efeito mais
            caro desta tela, e ele fica exatamente atrás do conteúdo que rola.
            O gradiente pinta o mesmo halo direto, sem camada e sem filtro. */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute top-0 left-1/2 -translate-x-1/2 w-[820px] h-[520px]"
          style={{ background: 'radial-gradient(50% 50% at 50% 40%, rgb(var(--accent) / 0.10), transparent 70%)' }}
        />

        <div className="relative max-w-6xl mx-auto px-4 pt-14 pb-16 md:pt-20 md:pb-24">
          <div className="grid lg:grid-cols-2 gap-12 lg:gap-10 items-center">

            <div>
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4 }}
                className="inline-flex items-center gap-2 border border-line rounded-full pl-2 pr-3 py-1 mb-6"
              >
                <LiveDot />
                <span className="text-[11px] font-medium text-ink-2">
                  Análise rodando nas ligas em temporada
                </span>
              </motion.div>

              <h1 className="font-display text-4xl md:text-5xl font-bold leading-[1.08] tracking-tight mb-5">
                {HEADLINE.map((line, i) => (
                  <motion.span
                    key={line}
                    className={`block ${i === 1 ? 'text-accent-ink' : ''}`}
                    initial={{ opacity: 0, y: 14 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.5, delay: i * 0.08, ease: 'easeOut' }}
                  >
                    {line}
                  </motion.span>
                ))}
              </h1>

              <motion.p
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.5, delay: 0.3 }}
                className="text-ink-2 text-base leading-relaxed mb-7 max-w-lg"
              >
                A Pick IA lê estatística real de cada jogo, calcula a probabilidade de cada
                mercado e compara com a odd que a casa está pagando. Só vira palpite o que
                tem valor esperado positivo.
              </motion.p>

              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.38 }}
                className="flex flex-col sm:flex-row gap-3 mb-4"
              >
                {/* O rótulo lidera pelo que a pessoa GANHA, não pelo trabalho
                    que ela tem. "Criar conta · 2 dias VIP grátis" abria com a
                    tarefa (criar conta) e empurrava a recompensa pro fim, atrás
                    de um separador · e "2 dias VIP grátis" solto ainda deixava
                    no ar se o grátis era o VIP ou a conta. Aqui o verbo é
                    testar, o objeto é o VIP e o preço aparece antes do clique. */}
                <Button to="/login?mode=register" size="lg" IconRight={ArrowRight}>
                  Testar o VIP grátis por 2 dias
                </Button>
                <Button to="/resultados" variant="ghost" size="lg">
                  Ver resultados reais
                </Button>
              </motion.div>

            </div>

            <div className="lg:pl-4">
              <FreePickHero revelar={topoPronto} onCarregou={marcarPronto} />
            </div>
          </div>

          {/* Fila, depois números · nessa ordem de propósito.
              O card acima é um pick só, os indicadores abaixo são o histórico
              inteiro; a fila é o presente entre os dois, e antes ela vinha
              depois de tudo, onde ninguém a lia como "está acontecendo". */}
          <div className="mt-12 md:mt-16">
            <NextGames revelar={topoPronto} onCarregou={marcarPronto} />
          </div>

          <div className="mt-8 md:mt-10">
            {/* Tudo que a faixa mostra sai do próprio summary, inclusive a
                quebra de VIP e free: uma linha do SELECT que já roda, nenhuma
                consulta a mais. Mesmo princípio que valia pro leagues_count,
                que antes obrigava a rota a montar a quebra por liga inteira. */}
            <StatsBand
              summary={data?.summary ?? null}
              leaguesCount={data?.summary?.leagues_count ?? 0}
              stakeLabel={data?.stake_label}
              loaded={topoPronto}
            />
          </div>
        </div>
      </section>

      <RecentResults summary={data?.summary ?? null} />

      <HowItWorks />

      <Products />

      <Leagues />

      <Plans monthly={monthly} />

      <FinalCTA />

      <Footer />

      {!ctaDismissed && ctaFaixa && <StickyMobileCTA onDismiss={() => setCtaDismissed(true)} {...ctaFaixa} />}
    </div>
  )
}
