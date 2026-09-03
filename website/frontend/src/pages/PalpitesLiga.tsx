import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Search } from 'lucide-react'
import api from '../services/api'
import PageShell from '../components/PageShell'
import PublicNav from '../components/PublicNav'
import { useAuth } from '../context/AuthContext'
import { EmptyState, SpinnerBlock } from '../components/ui'
import {
  ChamadaFinal, LinksDeLigas, ListaDeJogos, PlacarPublico, UltimosPicks,
  type DesempenhoPublico, type JogoPublico, type PickPublico,
} from '../components/PalpitesBlocos'

/*
 * /palpites/<liga>
 *
 * Uma página por campeonato coberto, com o recorte daquela liga. É o que
 * responde "palpites brasileirão", "palpites champions league" e companhia,
 * que é busca com intenção muito mais definida do que "palpites de futebol".
 *
 * Slug desconhecido NÃO cai no 404: o backend devolve `encontrada: false` com
 * a lista de ligas, e a tela oferece as que existem. Quem chegou aqui veio de
 * uma busca, e mandar essa visita pra tela de nada é jogar fora a única coisa
 * que a página tinha que fazer.
 */

interface LigaInfo {
  slug: string
  league_id: number
  name: string
  season: number | null
  ativa: boolean
}

interface LigaData {
  encontrada: boolean
  liga?: LigaInfo
  desempenho?: DesempenhoPublico
  jogos?: JogoPublico[]
  ultimos_picks?: PickPublico[]
  ligas?: LigaInfo[]
}

export default function PalpitesLiga() {
  const { slug = '' } = useParams()
  const { user } = useAuth()
  const [data, setData] = useState<LigaData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    api.get(`/public/palpites/${encodeURIComponent(slug)}`)
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [slug])

  const liga = data?.liga
  const nome = liga?.name ?? 'campeonato'
  const canonical = `https://pickia.com.br/palpites/${slug}`

  if (loading) {
    return (
      <PageShell
        title={`Palpites ${nome}`}
        noindex
        width="full"
        nav={user ? true : <PublicNav width="full" />}
      >
        <SpinnerBlock />
      </PageShell>
    )
  }

  if (!data?.encontrada) {
    return (
      <PageShell
        title="Palpites por campeonato | Pick IA"
        description="Escolha o campeonato e veja os jogos do dia, o histórico de acerto e os últimos palpites resolvidos."
        /* Slug inválido é uma URL que não deve existir no índice. A página
           continua servindo o visitante, mas não entra na busca. */
        noindex
        width="full"
        nav={user ? true : <PublicNav width="full" />}
        bar={{ title: 'Palpites por campeonato' }}
        mainClassName="space-y-10"
      >
        <EmptyState
          Icon={Search}
          title="Não cobrimos esse campeonato"
          description="Escolha um dos campeonatos abaixo para ver os jogos do dia e o histórico da IA."
          action={{ children: 'Ver palpites de hoje', to: '/palpites-de-futebol-hoje' }}
        />
        <LinksDeLigas ligas={data?.ligas ?? []} />
      </PageShell>
    )
  }

  const jogos = data.jogos ?? []
  /*
   * Liga cadastrada que ainda não tem nem histórico nem jogo na fila rende uma
   * página de zeros. Ela continua existindo pra quem chegar por link, mas fica
   * fora da busca: é por uma página assim que o site inteiro seria julgado.
   * O sitemap aplica o mesmo corte, do outro lado (palpites.slugs_publicos).
   */
  const vazia = (data.desempenho?.total ?? 0) === 0 && jogos.length === 0

  return (
    <PageShell
      title={`Palpites ${nome} Hoje e Histórico da IA | Pick IA`}
      description={`Palpites de ${nome} com análise estatística e IA. Jogos do dia, aproveitamento da IA neste campeonato e os últimos palpites resolvidos, com acerto e erro registrados.`}
      canonical={canonical}
      noindex={vazia}
      width="full"
      nav={user ? true : <PublicNav width="full" />}
      bar={{
        back: '/palpites-de-futebol-hoje',
        title: `Palpites ${nome}`,
        sub: liga?.ativa ? 'Temporada em andamento' : 'Competição encerrada, histórico mantido',
      }}
      mainClassName="space-y-10"
    >
      <section>
        <p className="text-sm text-ink-2 leading-relaxed max-w-3xl">
          Todos os palpites de {nome} publicados pela Pick IA ficam registrados nesta
          página, com o resultado de cada um. A análise usa a estatística real de cada
          time no campeonato e só publica o mercado quando a probabilidade calculada
          supera a odd oferecida.
        </p>
      </section>

      {data.desempenho && (
        <PlacarPublico dados={data.desempenho} rotulo={`Histórico público da IA em ${nome}.`} />
      )}

      <ListaDeJogos jogos={jogos} titulo={`Próximos jogos de ${nome}`} />

      <UltimosPicks
        picks={data.ultimos_picks ?? []}
        titulo={`Últimos palpites de ${nome}`}
      />

      <LinksDeLigas ligas={data.ligas ?? []} atual={liga?.slug} />

      <ChamadaFinal />
    </PageShell>
  )
}
