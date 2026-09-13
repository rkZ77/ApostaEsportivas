import { lazy, useCallback, useEffect, useLayoutEffect, useState } from 'react'
import { Helmet } from 'react-helmet-async'
import { X as XIcon } from 'lucide-react'

import api from '../services/api'
import SiteHeader from '../components/SiteHeader'
import Footer from '../components/Footer'
import SecaoAdiada from '../components/SecaoAdiada'
// Só o Button: o resto dos primitivos foi junto com as seções que saíram
// daqui (home/RecentResults.tsx e home/Plans.tsx).
import { Button } from '../components/ui'
import { usePlans, type Plan } from '../hooks/usePlans'
import { useAuth } from '../context/AuthContext'
import { encerrarBarraInicial } from '../lib/barraInicial'

import FreePickHero from '../home/FreePickHero'
import HeroTexto from '../home/HeroTexto'
import StatsBand, { type PublicSummary } from '../home/StatsBand'
import NextGames from '../home/NextGames'

/*
 * O QUE É `lazy()` AQUI, E POR QUÊ.
 *
 * Estas quatro seções vivem abaixo da dobra e entravam no chunk da Home ·
 * baixadas, avaliadas e montadas antes de o visitante ver o título. Como
 * `lazy()` dentro de <SecaoAdiada>, o chunk delas só é buscado quando a seção
 * vai nascer, e nascer é o que acontece quando ela chega perto da tela ou
 * quando a thread fica ociosa (ver components/SecaoAdiada.tsx).
 *
 * O hero e o topo (FreePickHero, NextGames, StatsBand) ficam de fora desta
 * lista de propósito: são a primeira tela, e adiá-los seria trocar um problema
 * de peso por uma tela vazia.
 */
const RecentResults = lazy(() => import('../home/RecentResults'))
const Plans      = lazy(() => import('../home/Plans'))
const HowItWorks = lazy(() => import('../home/HowItWorks'))
const Products   = lazy(() => import('../home/Products'))
const Leagues    = lazy(() => import('../home/Leagues'))
const FinalCTA   = lazy(() => import('../home/FinalCTA'))

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
 *
 * (O texto em si mora em home/HeroTexto.tsx desde 04/09 · ele é o único
 * pedaço da tela que o build pré-renderiza em HTML.)
 */

/*
 * O HERO JA ESTA NA TELA QUANDO ESTE ARQUIVO CARREGA?
 *
 * `scripts/prerender-hero.mjs` injeta o HeroTexto renderizado dentro do
 * <div id="root"> durante o build, com este atributo. Se ele está lá, o texto
 * já foi pintado (e já animou, em CSS) antes de o React existir · reanimar na
 * montagem seria um segundo fade no que a pessoa acabou de ler.
 *
 * Lido UMA vez, no módulo, e não dentro do componente: quando o Home renderiza,
 * o createRoot já esvaziou o container e a marca não está mais lá.
 */
const HERO_JA_PINTADO =
  typeof document !== 'undefined' && document.querySelector('[data-hero-estatico]') !== null


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

  /*
   * Tira da tela o hero que veio pronto no HTML.
   *
   * Ele mora FORA do #root (ver scripts/prerender-hero.mjs), então o React não
   * o apaga sozinho · e é exatamente por isso que ele sobrevive aos segundos
   * entre "o bundle subiu" e "a Home chegou".
   *
   * `useLayoutEffect`, e não `useEffect`: o efeito comum roda DEPOIS da
   * pintura, então existia um quadro com os dois heros na página, um embaixo
   * do outro, e a remoção no quadro seguinte puxava a página inteira para
   * cima. Medido em 04/09: CLS de 1,0 · a pior nota possível, causada por um
   * único quadro. O layout effect roda antes de pintar, então a troca nunca
   * chega à tela.
   */
  useLayoutEffect(() => { document.querySelector('[data-hero-estatico]')?.remove() }, [])

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

            <HeroTexto animar={!HERO_JA_PINTADO} />

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

      {/* Daqui pra baixo nada é montado antes da hora. As alturas reservadas
          saíram de medição no viewport de 390px · elas não precisam ser exatas
          (a seção cresce se precisar), precisam evitar que a barra de rolagem
          e o conteúdo seguinte pulem quando a seção nasce. */}
      <SecaoAdiada alturaMinima={770}><RecentResults summary={data?.summary ?? null} /></SecaoAdiada>

      <SecaoAdiada alturaMinima={920}><HowItWorks /></SecaoAdiada>

      <SecaoAdiada alturaMinima={510}><Products /></SecaoAdiada>

      <SecaoAdiada alturaMinima={270}><Leagues /></SecaoAdiada>

      <SecaoAdiada alturaMinima={1890}><Plans monthly={monthly} /></SecaoAdiada>

      <SecaoAdiada alturaMinima={580}><FinalCTA /></SecaoAdiada>

      <SecaoAdiada alturaMinima={420}><Footer /></SecaoAdiada>

      {!ctaDismissed && ctaFaixa && <StickyMobileCTA onDismiss={() => setCtaDismissed(true)} {...ctaFaixa} />}
    </div>
  )
}
