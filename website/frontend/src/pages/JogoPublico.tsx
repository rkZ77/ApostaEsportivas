import { useEffect, useState } from 'react'
import { Helmet } from 'react-helmet-async'
import { useNavigate, useParams } from 'react-router-dom'
import { CalendarDays, Lock } from 'lucide-react'
import api from '../services/api'
import PageShell from '../components/PageShell'
import PublicNav from '../components/PublicNav'
import { TeamLogo } from '../components/TeamLogo'
import { FormaPontos } from '../components/jogos/FormaPontos'
import { Button, EmptyState, Panel, PanelHead, SpinnerBlock } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { slugDoJogo } from '../lib/jogoPublico'

/*
 * /jogo/<fixture_id>/<casa>-x-<fora> · a vitrine pública do Raio-X (18/10/2026).
 *
 * O Pick IA se apresenta como plataforma de análise de futebol, e até aqui o
 * Google só enxergava pick: o Raio-X mora atrás do login e do Pro. Esta página
 * abre o básico que o usuário escolheu mostrar (horário, tabela, campanha em
 * casa e fora, forma dos últimos 5) e deixa o resto com cadeado, chamando pro
 * Raio-X completo. Tudo sai do banco, nenhuma chamada à API-Football · ver
 * backend/jogo_publico.py.
 */

interface Campanha {
  posicao: number | null
  pontos: number | null
  jogos: number | null
  saldo: number | null
  lado: {
    jogos: number | null
    vitorias: number | null
    empates: number | null
    derrotas: number | null
    gols_pro: number | null
    gols_contra: number | null
  }
}

interface Time {
  id: number
  nome: string
  forma: string[]
  tabela: Campanha | null
}

interface Jogo {
  fixture_id: number
  slug: string
  league_id: number
  league_name: string
  rodada: string | null
  /** Horário de Brasília sem fuso: ler por slice, nunca com new Date. */
  match_datetime: string | null
  status: string | null
  placar: { casa: number; fora: number } | null
  casa: Time
  fora: Time
}

const ORIGEM = 'https://pickia.com.br'
const DIAS = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb']

/** "sáb 18/10 às 16:00", lido direto da string pra não cair no fuso do aparelho. */
function quando(iso: string | null): string {
  if (!iso) return 'Data a confirmar'
  const [a, m, d] = iso.slice(0, 10).split('-').map(Number)
  const dia = DIAS[new Date(Date.UTC(a, m - 1, d)).getUTCDay()]
  return `${dia} ${String(d).padStart(2, '0')}/${String(m).padStart(2, '0')} às ${iso.slice(11, 16)}`
}

/** "Regular Season - 30" -> "Rodada 30". Fase de copa ("Round of 16", "Final")
 *  vem em inglês da API e fica de fora em vez de aparecer traduzida pela metade. */
function rodada(r: string | null): string | null {
  const m = r?.match(/^Regular Season\s*-\s*(\d+)$/i)
  return m ? `Rodada ${m[1]}` : null
}

const ITENS_DO_PRO = [
  'Estatística do jogo: gols, escanteios, cartões e finalizações de cada time',
  'Confronto direto entre os dois',
  'Escalação provável e desfalques',
  'Estatística de cada jogador',
  'Perfil do árbitro na temporada',
  'Resumo escrito pela IA',
]

export default function JogoPublico() {
  const { fixtureId, slug } = useParams()
  const navigate = useNavigate()
  const { user, isVip, isAdmin } = useAuth()
  const [jogo, setJogo] = useState<Jogo | null>(null)
  const [estado, setEstado] = useState<'carregando' | 'ok' | 'nao-existe' | 'erro'>('carregando')

  useEffect(() => {
    setEstado('carregando')
    api.get(`/public/jogo/${fixtureId}`)
      .then(r => { setJogo(r.data); setEstado('ok') })
      .catch(e => setEstado(e?.response?.status === 404 ? 'nao-existe' : 'erro'))
  }, [fixtureId])

  // Slug velho ou digitado errado: corrige a barra pro endereço canônico, sem
  // empilhar histórico.
  useEffect(() => {
    if (jogo && slug !== jogo.slug) navigate(`/jogo/${jogo.fixture_id}/${jogo.slug}`, { replace: true })
  }, [jogo, slug, navigate])

  const nav = user ? true : <PublicNav />

  if (estado !== 'ok' || !jogo) {
    return (
      <PageShell title="Jogo" noindex={estado !== 'carregando'} nav={nav}>
        {estado === 'carregando' ? <SpinnerBlock /> : (
          <EmptyState
            Icon={CalendarDays}
            title={estado === 'nao-existe' ? 'Jogo não encontrado' : 'Não foi possível carregar o jogo'}
            description={estado === 'nao-existe'
              ? 'Esse endereço não corresponde a nenhum jogo da nossa agenda.'
              : 'Pode ser instabilidade momentânea. Tente de novo em instantes.'}
            action={{ to: '/palpites-de-futebol-hoje', children: 'Ver os jogos de hoje' }}
          />
        )}
      </PageShell>
    )
  }

  const { casa, fora } = jogo
  const titulo = `${casa.nome} x ${fora.nome}`
  const dataTexto = quando(jogo.match_datetime)
  const encerrado = jogo.placar != null
  const canonica = `${ORIGEM}/jogo/${jogo.fixture_id}/${slugDoJogo(casa.nome, fora.nome)}`

  const pode = isVip || isAdmin || user?.plan === 'trial'
  const raioX = `/jogos/${jogo.fixture_id}?` + new URLSearchParams({
    home: String(casa.id), away: String(fora.id), league: String(jogo.league_id),
    liga: jogo.league_name, casa: casa.nome, fora: fora.nome, quando: jogo.match_datetime ?? '',
  }).toString()
  const chamada = pode
    ? { to: raioX, texto: 'Abrir o Raio-X completo' }
    : user
      ? { to: '/planos', texto: 'Desbloquear o Raio-X' }
      : { to: '/login?mode=register', texto: 'Testar o Pro grátis por 2 dias' }

  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'SportsEvent',
    name: titulo,
    sport: 'Futebol',
    url: canonica,
    ...(jogo.match_datetime ? { startDate: `${jogo.match_datetime.slice(0, 19)}-03:00` } : {}),
    homeTeam: { '@type': 'SportsTeam', name: casa.nome },
    awayTeam: { '@type': 'SportsTeam', name: fora.nome },
    superEvent: { '@type': 'SportsEvent', name: jogo.league_name },
  }

  return (
    <PageShell
      title={`${titulo}: análise e estatísticas`}
      description={`Análise de ${titulo} pela ${jogo.league_name}, ${dataTexto}: posição na tabela, campanha em casa e fora e forma recente dos dois times, com o Raio-X da Pick IA.`}
      canonical={canonica}
      nav={nav}
      bar={{ back: true, title: titulo, sub: `${jogo.league_name}, ${dataTexto}` }}
      mainClassName="space-y-6"
    >
      <Helmet>
        <script type="application/ld+json">{JSON.stringify(jsonLd)}</script>
      </Helmet>

      {/* Placar ou horário, com os dois escudos */}
      <section className="card p-5">
        <p className="text-[11px] text-ink-3 text-center mb-4 truncate">
          {jogo.league_name}{rodada(jogo.rodada) ? `, ${rodada(jogo.rodada)}` : ''}
        </p>
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">
          <Escudo time={casa} />
          <div className="text-center">
            {encerrado ? (
              <p className="font-mono text-2xl font-black tabular-nums text-ink-1">
                {jogo.placar!.casa} x {jogo.placar!.fora}
              </p>
            ) : (
              <p className="font-mono text-lg font-bold tabular-nums text-ink-1">
                {jogo.match_datetime?.slice(11, 16) ?? '--:--'}
              </p>
            )}
            <p className="text-[11px] text-ink-3 mt-0.5">{encerrado ? 'Encerrado' : dataTexto.split(' às ')[0]}</p>
          </div>
          <Escudo time={fora} />
        </div>
      </section>

      {/* O básico aberto */}
      <section>
        <h2 className="font-display text-base font-semibold text-ink-1 mb-3">Momento dos times</h2>
        <div className="grid gap-3 md:grid-cols-2">
          <Momento time={casa} lado="em casa" />
          <Momento time={fora} lado="fora de casa" />
        </div>
      </section>

      {/* O que fica no Pro */}
      <Panel>
        <PanelHead label="Raio-X completo do jogo" meta="Pro" />
        <ul className="px-5 py-2 divide-y divide-line/60">
          {ITENS_DO_PRO.map(item => (
            <li key={item} className="py-2.5 flex items-start gap-2.5 text-sm text-ink-2">
              <Lock className="w-3.5 h-3.5 mt-0.5 text-ink-4 shrink-0" aria-hidden />
              <span>{item}</span>
            </li>
          ))}
        </ul>
        <div className="px-5 pb-5 pt-2">
          <Button to={chamada.to} size="lg" block>{chamada.texto}</Button>
        </div>
      </Panel>
    </PageShell>
  )
}

function Escudo({ time }: { time: Time }) {
  return (
    <div className="flex flex-col items-center gap-2 min-w-0">
      <TeamLogo id={time.id} name={time.nome} size={44} />
      <p className="text-sm font-semibold text-ink-1 text-center leading-tight line-clamp-2">{time.nome}</p>
      {time.tabela?.posicao != null && (
        <p className="text-[11px] text-ink-3">{time.tabela.posicao}º na tabela</p>
      )}
    </div>
  )
}

function Momento({ time, lado }: { time: Time; lado: string }) {
  const t = time.tabela
  const l = t?.lado
  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center gap-2 min-w-0">
        <TeamLogo id={time.id} name={time.nome} size={20} />
        <p className="text-sm font-semibold text-ink-1 truncate">{time.nome}</p>
      </div>

      <div className="flex items-center justify-between gap-3">
        <span className="text-xs text-ink-3">Últimos 5 na competição</span>
        {time.forma.length ? <FormaPontos forma={time.forma} /> : <span className="text-xs text-ink-4">Sem jogos ainda</span>}
      </div>

      {t ? (
        <dl className="grid grid-cols-3 gap-2 text-center">
          <Dado rotulo="Posição" valor={t.posicao != null ? `${t.posicao}º` : '-'} />
          <Dado rotulo="Pontos" valor={t.pontos ?? '-'} />
          <Dado rotulo="Saldo" valor={t.saldo != null ? (t.saldo > 0 ? `+${t.saldo}` : t.saldo) : '-'} />
        </dl>
      ) : (
        <p className="text-xs text-ink-4">Competição sem tabela de pontos.</p>
      )}

      {l?.jogos ? (
        <p className="text-xs text-ink-2 leading-relaxed">
          <span className="text-ink-3">Campanha {lado}: </span>
          {l.vitorias ?? 0}V {l.empates ?? 0}E {l.derrotas ?? 0}D em {l.jogos} jogos,
          {' '}{l.gols_pro ?? 0} gols marcados e {l.gols_contra ?? 0} sofridos.
        </p>
      ) : null}
    </div>
  )
}

function Dado({ rotulo, valor }: { rotulo: string; valor: React.ReactNode }) {
  return (
    <div className="rounded-lg bg-surface-2 py-2">
      <dt className="text-[10px] text-ink-3">{rotulo}</dt>
      <dd className="font-mono text-sm font-bold tabular-nums text-ink-1">{valor}</dd>
    </div>
  )
}
