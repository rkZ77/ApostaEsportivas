import { useEffect, useState } from 'react'
import { Helmet } from 'react-helmet-async'
import api from '../services/api'
import PageShell from '../components/PageShell'
import PublicNav from '../components/PublicNav'
import { useAuth } from '../context/AuthContext'
import { SpinnerBlock } from '../components/ui'
import {
  ChamadaFinal, LinksDeLigas, ListaDeJogos, PlacarPublico, UltimosPicks,
  type DesempenhoPublico, type JogoPublico, type PickPublico,
} from '../components/PalpitesBlocos'

/*
 * /palpites-de-futebol-hoje
 *
 * A porta de entrada de busca do site. A home vende o produto; esta página
 * responde a frase que as pessoas realmente digitam ("palpites de futebol
 * hoje") com o que o motor já tem: os jogos do dia na fila, o placar público
 * acumulado e os últimos palpites resolvidos.
 *
 * A URL é a palavra-chave, e por isso ela é longa e feia de propósito. É o
 * único endereço do site que uma pessoa consegue adivinhar.
 */

interface LigaResumo {
  slug: string
  league_id: number
  name: string
  ativa: boolean
  picks_resolvidos: number
  win_rate: number | null
  tem_jogo_hoje: boolean
}

interface HubData {
  ligas: LigaResumo[]
  jogos: JogoPublico[]
  desempenho: DesempenhoPublico
  ultimos_picks: PickPublico[]
}

const URL_CANONICA = 'https://pickia.com.br/palpites-de-futebol-hoje'

export default function PalpitesHoje() {
  const { user } = useAuth()
  const [data, setData] = useState<HubData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/public/palpites')
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [])

  const jogos = data?.jogos ?? []
  const ligas = data?.ligas ?? []

  /*
   * ItemList com os jogos do dia. É o dado estruturado que dá ao Google o
   * motivo de tratar esta página como "de hoje": ela muda todo dia e diz
   * quais partidas cobre.
   */
  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'ItemList',
    name: 'Jogos de futebol analisados hoje pela Pick IA',
    numberOfItems: jogos.length,
    itemListElement: jogos.map((j, i) => ({
      '@type': 'ListItem',
      position: i + 1,
      name: `${j.home_team} x ${j.away_team}`,
    })),
  }

  return (
    <PageShell
      title="Palpites de Futebol Hoje com Análise da IA | Pick IA"
      description="Palpites de futebol de hoje com análise estatística e inteligência artificial. Veja os jogos na fila da IA, o histórico público de acerto por campeonato e os últimos palpites resolvidos."
      canonical={URL_CANONICA}
      width="full"
      nav={user ? true : <PublicNav width="full" />}
      bar={{
        title: 'Palpites de futebol hoje',
        sub: 'Os jogos do dia, o histórico público e o aproveitamento por campeonato',
      }}
      mainClassName="space-y-10"
    >
      <Helmet>
        <script type="application/ld+json">{JSON.stringify(jsonLd)}</script>
      </Helmet>

      <section>
        <p className="text-sm text-ink-2 leading-relaxed max-w-3xl">
          A Pick IA analisa os jogos de futebol do dia com estatística real de cada time,
          calcula a probabilidade de cada mercado e compara com a odd que a casa está
          pagando. Só vira palpite o que tem valor esperado positivo. Todos os palpites
          publicados ficam registrados, acerto e erro, e o placar abaixo sai desse mesmo
          histórico.
        </p>
      </section>

      {loading ? (
        <SpinnerBlock />
      ) : (
        <>
          {data && <PlacarPublico dados={data.desempenho} rotulo="Histórico público acumulado, todos os campeonatos." />}
          <ListaDeJogos jogos={jogos} comLiga titulo="Jogos de hoje na fila da análise" />
          <LinksDeLigas ligas={ligas} />
          <UltimosPicks
            picks={data?.ultimos_picks ?? []}
            comLiga
            titulo="Últimos palpites resolvidos"
          />
          <ChamadaFinal />
        </>
      )}
    </PageShell>
  )
}
