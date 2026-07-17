import { Link } from 'react-router-dom'
import { useState, useEffect, useRef } from 'react'
import { Helmet } from 'react-helmet-async'
import { Menu, X as XIcon, UserPlus, Zap, TrendingUp, Trophy, Gift, ArrowRight } from 'lucide-react'
import api from '../services/api'
import Footer from '../components/Footer'
import { getResultStyle, PICK_TYPE_CLS } from '../utils/resultStyle'

const TEAM_LOGO = (id?: number | null) =>
  id ? `/api/proxy/team/${id}.png` : null
const LEAGUE_LOGO = (id: number) =>
  id === 1 ? '/logo-copa-mundo.png' : `/api/proxy/league/${id}.png`

// Ícones
function Check() {
  return (
    <svg className="w-4 h-4 text-green-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  )
}
function X() {
  return (
    <svg className="w-4 h-4 text-zinc-700 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
    </svg>
  )
}

// Tipos
interface RecentTip {
  match_date: string
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
  summary: { total: number; greens: number; profit: number; roi: number }
  recent: RecentTip[]
  counts?: { vip_total: number; free_total: number; multipla_total: number; alavancagem_total: number }
}

// Helpers
const SRC_LBL: Record<string, string> = { vip: 'VIP', free: 'Free', multiplas: 'Múlt.', alavancagem: 'Alav.' }

// Social proof stats · bloco de 4 métricas em tempo real
function SocialProofStats() {
  const [summary, setSummary] = useState<{ total: number; greens: number; profit: number } | null>(null)
  const [loaded, setLoaded] = useState(false)
  useEffect(() => {
    api.get('/public/results')
      .then(r => { setSummary(r.data?.summary ?? null); setLoaded(true) })
      .catch(() => setLoaded(true))
  }, [])

  if (!loaded) return <div className="h-20 mt-6 bg-zinc-900/40 rounded-2xl animate-pulse" />

  const winRate = summary && summary.total > 0 ? ((summary.greens / summary.total) * 100).toFixed(0) : null
  const reds    = summary ? summary.total - summary.greens : 0

  if (!summary || summary.total === 0) {
    return (
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 mt-5">
        <div className="flex items-center gap-1.5 text-xs text-zinc-500">
          <span className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse" />
          Picks diários gerados por IA · Auditável publicamente
        </div>
      </div>
    )
  }

  return (
    <div className="mt-6 grid grid-cols-2 sm:grid-cols-4 gap-2">
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-3 text-center">
        <p className="text-xl font-black text-green-500">{winRate}%</p>
        <p className="text-[10px] text-zinc-500 mt-0.5 uppercase tracking-wide">Win Rate</p>
      </div>
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-3 text-center">
        <p className="text-xl font-black text-white">{summary.total}</p>
        <p className="text-[10px] text-zinc-500 mt-0.5 uppercase tracking-wide">Picks</p>
      </div>
      <div className="bg-zinc-900 border border-green-500/20 rounded-xl p-3 text-center">
        <p className="text-xl font-black text-green-400">{summary.greens}</p>
        <p className="text-[10px] text-zinc-500 mt-0.5 uppercase tracking-wide">GREEN</p>
      </div>
      <div className="bg-zinc-900 border border-red-500/20 rounded-xl p-3 text-center">
        <p className="text-xl font-black text-red-400">{reds}</p>
        <p className="text-[10px] text-zinc-500 mt-0.5 uppercase tracking-wide">RED</p>
      </div>
    </div>
  )
}

// 3 passos · jornada do usuário
function ThreeSteps() {
  return (
    <section id="como-funciona" className="py-16 bg-black border-b border-zinc-800/60">
      <div className="max-w-5xl mx-auto px-4">
        <p className="text-center text-sm text-zinc-500 font-medium mb-10">Como funciona</p>
        <div className="grid md:grid-cols-3 gap-5">
          {([
            { n: '1', Icon: UserPlus, title: 'Cria sua conta', desc: 'Cadastro em menos de 1 minuto. Ganhe 2 dias de acesso VIP completo para testar tudo.', color: 'text-green-500', border: 'border-green-500/20', iconBg: 'bg-green-500/10' },
            { n: '2', Icon: Zap,      title: 'Recebe picks todo dia', desc: 'A IA analisa os jogos e entrega os melhores picks direto no app: VIP, Múltiplas e Alavancagem.', color: 'text-blue-400', border: 'border-blue-400/20', iconBg: 'bg-blue-400/10' },
            { n: '3', Icon: TrendingUp, title: 'Acompanha e lucra', desc: 'Veja o resultado de cada pick em tempo real. Histórico completo, transparência total e estratégia de banca.', color: 'text-yellow-400', border: 'border-yellow-400/20', iconBg: 'bg-yellow-400/10' },
          ] as const).map(({ n, Icon, title, desc, color, border, iconBg }) => (
            <div key={n} className={`border rounded-2xl p-6 text-center ${border}`}>
              <div className={`inline-flex items-center justify-center w-12 h-12 rounded-2xl mb-4 ${iconBg}`}>
                <Icon className={`w-6 h-6 ${color}`} />
              </div>
              <div className={`text-sm font-black ${color} mb-2 opacity-60`}>{n}</div>
              <h3 className="text-base font-black text-white mb-2">{title}</h3>
              <p className="text-zinc-400 text-sm leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>
        <div className="text-center mt-8">
          <Link to="/login?mode=register" className="inline-flex items-center gap-2 bg-green-500 hover:bg-green-400 text-black font-black px-7 py-3 rounded-xl text-sm transition-colors">
            Começar agora
          </Link>
        </div>
      </div>
    </section>
  )
}

// Sticky CTA mobile (fixo no rodapé, apenas mobile)
function StickyMobileCTA() {
  const [dismissed, setDismissed] = useState(false)
  if (dismissed) return null
  return (
    <div className="fixed bottom-0 inset-x-0 z-50 sm:hidden bg-zinc-950/98 backdrop-blur-md border-t border-zinc-800 px-4 py-3 flex items-center gap-3 shadow-[0_-4px_24px_rgba(0,0,0,0.6)]">
      <div className="flex-1 min-w-0">
        <p className="text-white text-xs font-black leading-none">Começar teste VIP</p>
        <p className="text-green-500 text-[10px] font-semibold mt-0.5">
          2 dias grátis · Brasileirão + Premier League
        </p>
      </div>
      <Link to="/login?mode=register" className="bg-green-500 hover:bg-green-400 text-black font-black text-xs px-5 py-3 rounded-xl transition-colors whitespace-nowrap">
        Criar conta
      </Link>
      <button onClick={() => setDismissed(true)} className="text-zinc-600 hover:text-zinc-400 p-1 shrink-0" aria-label="Fechar">
        <XIcon className="w-4 h-4" />
      </button>
    </div>
  )
}

// Ligas ativas (do banco)
interface LeagueTeaser { league_id: number; name: string; season: number; logo_url: string }

function ActiveLeagues() {
  const [leagues, setLeagues] = useState<LeagueTeaser[]>([])

  useEffect(() => {
    api.get('/public/leagues')
      .then(r => setLeagues(r.data ?? []))
      .catch(() => {})
  }, [])

  if (!leagues.length) return null

  return (
    <section className="border-y border-zinc-800/60 bg-zinc-950 py-14">
      <div className="max-w-5xl mx-auto px-4">
        <div className="text-center mb-8">
          <h2 className="text-2xl font-black mb-2">Ligas e torneios cobertos</h2>
          <p className="text-zinc-400 text-sm max-w-lg mx-auto">
            A cobertura entra automaticamente assim que a temporada de cada liga estiver rolando ·
            hoje a IA já analisa:
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-center gap-8">
          {leagues.map(({ league_id, name, logo_url }) => (
            <div key={league_id} className="flex flex-col items-center gap-2">
              <img
                src={logo_url}
                alt={name}
                className="w-10 h-10 object-contain"
                onError={e => (e.currentTarget.style.display = 'none')}
              />
              <div className="text-center">
                <p className="text-xs font-semibold text-zinc-300 leading-tight">{name}</p>
                <p className="text-[10px] text-green-500 font-bold">Ativo</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function TeamLogo({ id, name }: { id?: number | null; name: string }) {
  const src = TEAM_LOGO(id)
  if (!src) return null
  return (
    <img src={src} alt={name} width={18} height={18} loading="lazy"
      className="w-4.5 h-4.5 object-contain shrink-0"
      onError={e => (e.currentTarget.style.display = 'none')} />
  )
}

// Últimos 6 resultados
function RecentResults() {
  const [data, setData] = useState<PublicData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/public/results')
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [])

  const s = data?.summary
  const recent6 = (data?.recent ?? []).slice(0, 6)

  return (
    <section id="resultados" className="py-24 bg-zinc-950 border-y border-zinc-800/60">
      <div className="max-w-5xl mx-auto px-4">
        <div className="text-center mb-12">
          <h2 className="text-3xl md:text-4xl font-black mb-3">Resultados reais, verificáveis</h2>
          <p className="text-zinc-400 text-sm max-w-lg mx-auto">
            Todos os picks ficam registrados. Win rate auditável, qualquer pessoa pode conferir.
          </p>
        </div>

        {/* Lista */}
        {loading ? (
          <div className="flex justify-center py-12">
            <div className="w-7 h-7 border-2 border-zinc-700 border-t-green-500 rounded-full animate-spin" />
          </div>
        ) : recent6.length > 0 ? (
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden">
            <div className="px-5 py-3 border-b border-zinc-800 flex items-center justify-between">
              <span className="text-xs font-bold text-zinc-400 uppercase tracking-wider">Últimas 6 dicas finalizadas</span>
              <span className="text-xs text-zinc-600">Atualizado automaticamente</span>
            </div>
            <div className="divide-y divide-zinc-800/50">
              {recent6.map((tip, i) => (
                <div key={i} className="flex items-center gap-2 px-3 sm:px-5 py-3">
                  <div className="w-10 sm:w-14 shrink-0 text-center">
                    <span className="text-[10px] sm:text-xs text-zinc-500">
                      {new Date(tip.match_date).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })}
                    </span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1 mb-0.5 flex-wrap">
                      <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border shrink-0 ${PICK_TYPE_CLS[tip.source] ?? ''}`}>
                        {SRC_LBL[tip.source] ?? tip.source}
                      </span>
                      <TeamLogo id={tip.home_team_id} name={tip.home_team_name} />
                      <span className="text-xs sm:text-sm font-semibold text-white truncate">{tip.home_team_name}</span>
                      {tip.away_team_name && tip.away_team_name !== '--' && (
                        <>
                          <span className="text-zinc-600 text-[10px] shrink-0">vs</span>
                          <TeamLogo id={tip.away_team_id} name={tip.away_team_name} />
                          <span className="text-xs sm:text-sm font-semibold text-white truncate">{tip.away_team_name}</span>
                        </>
                      )}
                    </div>
                    <p className="text-[10px] sm:text-xs text-zinc-500 truncate">
                      {tip.market && tip.market !== '--' ? tip.market : ''}
                      {tip.line && tip.line !== '--' ? ` ${tip.line}` : ''}
                      {' · '}{Number(tip.odd).toFixed(2)}
                    </p>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {(() => {
                      const rs = getResultStyle(tip.result)
                      return (
                        <span className={`text-[10px] sm:text-xs font-black px-1.5 sm:px-2 py-0.5 rounded-lg border ${rs ? `${rs.bg} ${rs.border} ${rs.text}` : 'text-zinc-500'}`}>
                          {rs ? rs.label : tip.result}
                        </span>
                      )
                    })()}
                  </div>
                </div>
              ))}
            </div>
            <div className="px-5 py-4 border-t border-zinc-800 text-center bg-zinc-950/50 flex items-center justify-center gap-5">
              <Link to="/resultados" className="text-sm text-zinc-400 hover:text-white font-semibold transition-colors">
                Ver histórico completo
              </Link>
              <span className="text-zinc-700">·</span>
              <Link to="/login?mode=register" className="text-sm text-green-500 hover:text-green-400 font-bold transition-colors">
                Criar conta grátis
              </Link>
            </div>
          </div>
        ) : (
          <p className="text-center text-zinc-600 text-sm py-8">Nenhum resultado ainda.</p>
        )}

        {/* Simulação de lucro */}
        {s && s.profit > 1 && (() => {
          const unidade = 10
          const inicial = 600
          const ganho = Math.round(s.profit * unidade)
          const final_ = inicial + ganho
          const pct = ((ganho / inicial) * 100).toFixed(0)
          return (
            <div className="mt-8 bg-zinc-900 border border-green-500/20 rounded-2xl p-5">
              <div className="flex items-start justify-between gap-3 mb-4 flex-wrap">
                <div>
                  <p className="text-xs text-zinc-500 uppercase tracking-wider font-semibold">Simulação · R$10 por unidade</p>
                  <p className="text-[10px] text-zinc-700 mt-0.5">Seguindo todos os picks desde o início</p>
                </div>
                <span className="bg-green-500/10 border border-green-500/20 text-green-400 text-[10px] font-black px-2 py-1 rounded-full shrink-0">
                  Atualizado automaticamente
                </span>
              </div>
              <div className="flex items-center gap-3 sm:gap-6">
                <div className="text-center shrink-0">
                  <p className="text-xl sm:text-2xl font-black text-zinc-400">R${inicial}</p>
                  <p className="text-[10px] text-zinc-600 mt-0.5">banca inicial</p>
                </div>
                <div className="flex-1 flex flex-col items-center gap-1">
                  <span className="text-green-400 text-sm font-black">+R${ganho}</span>
                  <div className="w-full border-t-2 border-dashed border-green-500/30" />
                  <span className="text-zinc-600 text-[10px]">{s.total} picks · +{pct}%</span>
                </div>
                <div className="text-center shrink-0">
                  <p className="text-xl sm:text-2xl font-black text-green-400">R${final_}</p>
                  <p className="text-[10px] text-zinc-600 mt-0.5">banca atual</p>
                </div>
              </div>
            </div>
          )
        })()}
      </div>
    </section>
  )
}

// ── Dica do Dia gratis (teaser publico, sem login) ────────────────────────
interface FreePickToday {
  id: number
  home_team_name: string
  away_team_name: string
  home_team_id?: number | null
  away_team_id?: number | null
  odd: number
  result: string | null
}

function FreePickTeaserCard() {
  const [pick, setPick] = useState<FreePickToday | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/public/free-pick-today')
      .then(r => setPick(r.data ?? null))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  if (loading || !pick) return null

  const rs = getResultStyle(pick.result)

  return (
    <div className="relative">
      <div className="absolute -inset-3 bg-gradient-to-br from-green-500/15 to-yellow-400/10 rounded-3xl blur-xl" />
      <div className="relative bg-zinc-950 border border-green-500/30 rounded-2xl p-6 sm:p-8 text-center">
        <div className="inline-flex items-center gap-2 bg-green-500/10 border border-green-500/20 rounded-full px-4 py-1.5 mb-5 flex-wrap justify-center">
          <Gift className="w-3.5 h-3.5 text-green-400" />
          <span className="text-green-400 text-xs font-bold">Dica do Dia · grátis, sem precisar de conta</span>
          {rs && (
            <span className={`text-[10px] font-black px-2 py-0.5 rounded-full border ${rs.bg} ${rs.border} ${rs.text}`}>
              {rs.label} {rs.emoji}
            </span>
          )}
        </div>
        <p className="text-lg sm:text-xl font-black text-white mb-1 flex items-center justify-center gap-2 flex-wrap">
          <TeamLogo id={pick.home_team_id} name={pick.home_team_name} />
          {pick.home_team_name} <span className="text-zinc-600">x</span> {pick.away_team_name}
          <TeamLogo id={pick.away_team_id} name={pick.away_team_name} />
        </p>
        <p className="text-zinc-500 text-xs mb-6">
          Pick gerado por IA hoje · odd {Number(pick.odd).toFixed(2)}
        </p>
        <Link
          to={`/p/free/${pick.id}`}
          className="inline-flex items-center gap-2 bg-green-500 hover:bg-green-400 text-black font-black px-6 py-3 rounded-xl text-sm transition-colors"
        >
          Ver a análise completa
          <ArrowRight className="w-4 h-4" />
        </Link>
        <p className="text-[11px] text-zinc-600 mt-3">
          Crie sua conta grátis em segundos pra ver o mercado e a análise completa da IA
        </p>
      </div>
    </div>
  )
}

// No desktop o card entra dentro do hero (embaixo dos Bastidores da IA,
// preenchendo o espaco vazio que sobrava ali). No mobile a maioria dos
// usuarios acessa (Android/Safari web) o hero e so texto -- essa versao
// em secao cheia garante que o pick gratis apareca pra eles tambem.
function FreePickTeaser() {
  return (
    <section className="py-14 md:hidden">
      <div className="max-w-2xl mx-auto px-4">
        <FreePickTeaserCard />
      </div>
    </section>
  )
}

// ── Leaderboard Teaser ───────────────────────────────────────────────────
interface LeaderEntry { name: string; avatar_url?: string; total: number; greens: number; win_rate: number; yield_roi: number }

function LeaderboardTeaser() {
  const [leaders, setLeaders] = useState<LeaderEntry[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/public/leaderboard')
      .then(r => setLeaders(r.data ?? []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  if (!loading && leaders.length === 0) return null

  const rankCls = ['bg-yellow-400 text-black', 'bg-zinc-300 text-black', 'bg-orange-400 text-black']

  return (
    <section className="py-16 bg-black border-y border-zinc-800/60">
      <div className="max-w-2xl mx-auto px-4">
        <div className="text-center mb-8">
          <p className="text-sm font-bold text-yellow-400 mb-2 flex items-center justify-center gap-1.5">
            <Trophy className="w-4 h-4" /> Ranking de usuários
          </p>
          <h2 className="text-2xl font-black text-white">Quem está ganhando mais</h2>
          <p className="text-zinc-500 text-sm mt-2">Top apostadores da plataforma este mês</p>
        </div>
        {loading ? (
          <div className="flex justify-center py-8">
            <div className="w-6 h-6 border-2 border-zinc-700 border-t-yellow-400 rounded-full animate-spin" />
          </div>
        ) : (
          <div className="space-y-3">
            {leaders.slice(0, 3).map((l, i) => (
              <div key={i} className="flex items-center gap-4 bg-zinc-950 border border-zinc-800 rounded-2xl px-5 py-4">
                <span className={`text-xs font-black w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${rankCls[i] ?? 'bg-zinc-800 text-zinc-400'}`}>
                  {i + 1}
                </span>
                <div className="w-9 h-9 rounded-full bg-zinc-800 flex items-center justify-center text-sm font-black text-zinc-400 shrink-0 overflow-hidden">
                  {l.avatar_url
                    ? <img src={l.avatar_url} alt={l.name} className="w-full h-full object-cover" onError={e => (e.currentTarget.style.display = 'none')} />
                    : l.name[0]?.toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-bold text-white truncate">{l.name}</p>
                  <p className="text-[11px] text-zinc-500">{l.total} picks · {l.greens} greens</p>
                </div>
                <div className="text-right shrink-0">
                  <p className={`text-lg font-black ${l.yield_roi >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {l.yield_roi >= 0 ? '+' : ''}{l.yield_roi.toFixed(1)}%
                  </p>
                  <p className="text-[10px] text-zinc-600">Yield ROI</p>
                </div>
                <div className="text-right shrink-0 hidden sm:block">
                  <p className="text-base font-black text-white">{l.win_rate}%</p>
                  <p className="text-[10px] text-zinc-600">Win rate</p>
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="text-center mt-6">
          <Link to="/login" className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors">
            Entre para ver seu ranking
          </Link>
        </div>
      </div>
    </section>
  )
}

// ── Activity Ticker (dados reais do backend) ──────────────────────────────
const FALLBACK_ACTIVITIES = [
  'João acabou de ativar o teste VIP',
  'Maria criou uma conta agora',
  'Carlos está acompanhando ao vivo',
  'Rodrigo seguiu o pick VIP de hoje',
  'Ana ativou o acesso VIP',
]
function ActivityTicker() {
  const [events, setEvents] = useState<{ name: string; verb: string }[]>([])
  const [totalUsers, setTotalUsers] = useState<number | null>(null)
  const [idx, setIdx] = useState(0)
  const [fade, setFade] = useState(true)

  useEffect(() => {
    api.get('/public/activity')
      .then(r => {
        if (r.data?.events?.length) {
          setEvents(r.data.events)
          setTotalUsers(r.data.total_users ?? null)
        }
      })
      .catch(() => {})
  }, [])

  const items = events.length > 0
    ? events.map(e => `${e.name} ${e.verb}`)
    : FALLBACK_ACTIVITIES

  useEffect(() => {
    const t = setInterval(() => {
      setFade(false)
      setTimeout(() => { setIdx(i => (i + 1) % items.length); setFade(true) }, 300)
    }, 4000)
    return () => clearInterval(t)
  }, [items.length])

  return (
    <div className="border-y border-zinc-800/60 bg-zinc-950/60 py-2.5">
      <div className="flex items-center justify-center gap-3">
        <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse shrink-0" />
        <p className={`text-xs text-zinc-400 transition-opacity duration-300 ${fade ? 'opacity-100' : 'opacity-0'}`}>
          {items[idx]}
        </p>
        {totalUsers !== null && totalUsers > 0 && (
          <span className="text-[10px] text-zinc-600 hidden sm:block">· {totalUsers}+ usuários cadastrados</span>
        )}
      </div>
    </div>
  )
}

// ── Bastidores da IA ─────────────────────────────────────────────────────
const BAST = [
  { text: 'Coletando dados dos jogos...', val: 'jogos do dia' },
  { text: 'Analisando estatísticas...', val: '18.412 dados' },
  { text: 'Calculando valor esperado (EV)...', val: 'edge positivo' },
  { text: 'Validando confiança mínima...', val: '≥ 60%' },
  { text: 'Gerando picks do dia...', val: '' },
]
function BastidoresAnimation() {
  const [step, setStep] = useState(0)
  const [picks, setPicks] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setStep(s => (s + 1) % BAST.length), 1100)
    return () => clearInterval(t)
  }, [])
  useEffect(() => {
    if (step !== BAST.length - 1) { setPicks(0); return }
    let n = 0
    const t = setInterval(() => { n++; setPicks(n); if (n >= 4) clearInterval(t) }, 220)
    return () => clearInterval(t)
  }, [step])
  return (
    <div className="bg-zinc-950 border border-zinc-800 rounded-2xl p-5 font-mono text-xs space-y-2">
      <div className="flex items-center gap-2 mb-3">
        <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
        <span className="text-green-400 font-bold">Pick IA Engine · rodando agora</span>
      </div>
      {BAST.map(({ text, val }, i) => (
        <div key={i} className={`flex items-center justify-between gap-2 transition-all duration-300 ${i <= step ? 'opacity-100' : 'opacity-15'}`}>
          <span className={i < step ? 'text-zinc-500' : i === step ? 'text-white' : 'text-zinc-700'}>
            <span className="text-green-500 mr-1.5">{i < step ? '✓' : i === step ? '>' : ' '}</span>{text}
          </span>
          <span className="text-green-400 shrink-0 text-[10px]">
            {i < step ? val : (i === step && step === BAST.length - 1 && picks > 0) ? `${picks} picks` : ''}
          </span>
        </div>
      ))}
    </div>
  )
}


// Landing
export default function Landing() {
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const [chatDemo, setChatDemo] = useState(0)
  const [openFaq, setOpenFaq] = useState<number | null>(null)
  useEffect(() => {
    const t = setInterval(() => setChatDemo(n => (n + 1) % 3), 3000)
    return () => clearInterval(t)
  }, [])

  const chatMessages = [
    { q: 'Qual o melhor pick para hoje no Brasileirão?', a: 'Analisando os jogos do Brasileirão de hoje... Flamengo x Palmeiras: Gols Over 2.5 @ 1.82 com 74% de confiança. Ambos os times marcaram em 80% dos confrontos recentes.' },
    { q: 'Como está a forma do Flamengo nos últimos 5 jogos?', a: 'Flamengo: 4V 1E 0D nos últimos 5. Média de 2.4 gols por jogo, 1.2 sofridos. Força ofensiva acima da média da liga. Pick recomendado: Gols Over 1.5.' },
    { q: 'Explica a Alavancagem', a: 'A Alavancagem começa com R$50 e reinveste 100% do lucro a cada GREEN. Uma sequência de 5 greens transforma R$50 em +R$300. Reset automático no RED.' },
  ]

  return (
    <>
    <Helmet>
      <title>Pick IA · Picks de Futebol com Inteligência Artificial</title>
      <meta name="description" content="Picks de futebol gerados por IA com análise estatística real. Cobertura de Brasileirão e Premier League. VIP, múltiplas, alavancagem e picks gratuitos. Teste grátis por 2 dias." />
      <link rel="canonical" href="https://pickia.com.br/" />
    </Helmet>
    <div className="min-h-screen bg-black text-white overflow-x-hidden">

      <nav className="border-b border-zinc-800/60 sticky top-0 z-50 bg-black/95 backdrop-blur-md" ref={menuRef}>
        <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <img src="/logo.png" alt="PickIA" className="w-9 h-9 rounded-full object-cover" />
            <span className="font-black text-lg tracking-tight">Pick<span className="text-green-500">IA</span></span>
            <span className="hidden sm:inline-flex items-center gap-1.5 bg-yellow-400/10 border border-yellow-400/20 text-yellow-400 text-[10px] font-semibold px-2 py-0.5 rounded-full">
              <span className="w-1.5 h-1.5 bg-yellow-400 rounded-full animate-pulse" />
              Brasileirão · Premier League
            </span>
          </div>
          <div className="flex items-center gap-5">
            <a href="#resultados" className="text-zinc-400 hover:text-white text-sm font-medium transition-colors hidden sm:block">Resultados</a>
            <a href="#como-funciona" className="text-zinc-400 hover:text-white text-sm font-medium transition-colors hidden sm:block">Como funciona</a>
            <a href="#planos" className="text-zinc-400 hover:text-white text-sm font-medium transition-colors hidden sm:block">Planos</a>
            <Link to="/login" className="text-zinc-400 hover:text-white text-sm font-medium transition-colors px-2 hidden sm:block">Entrar</Link>
            <Link to="/login?mode=register" className="bg-green-500 hover:bg-green-400 text-black font-black text-sm px-5 py-2 rounded-xl transition-colors hidden sm:block">
              Criar conta grátis
            </Link>
            {/* Mobile: CTA + hambúrguer */}
            <Link to="/login?mode=register" className="bg-green-500 hover:bg-green-400 text-black font-black text-xs px-4 py-2 rounded-xl transition-colors sm:hidden">
              Grátis 2 dias
            </Link>
            <button
              onClick={() => setMenuOpen(o => !o)}
              className="sm:hidden p-2 text-zinc-400 hover:text-white transition-colors"
              aria-label="Menu"
            >
              {menuOpen ? <XIcon className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
            </button>
          </div>
        </div>

        {/* Mobile dropdown */}
        {menuOpen && (
          <div className="sm:hidden border-t border-zinc-800 bg-black/98 px-4 py-3 space-y-1">
            <a href="#resultados" onClick={() => setMenuOpen(false)}
              className="flex items-center gap-3 px-3 py-3 rounded-xl text-zinc-300 hover:text-white hover:bg-zinc-900 transition-colors text-sm font-medium">
              Resultados
            </a>
            <a href="#como-funciona" onClick={() => setMenuOpen(false)}
              className="flex items-center gap-3 px-3 py-3 rounded-xl text-zinc-300 hover:text-white hover:bg-zinc-900 transition-colors text-sm font-medium">
              Como funciona
            </a>
            <a href="#planos" onClick={() => setMenuOpen(false)}
              className="flex items-center gap-3 px-3 py-3 rounded-xl text-zinc-300 hover:text-white hover:bg-zinc-900 transition-colors text-sm font-medium">
              Planos
            </a>
            <div className="border-t border-zinc-800 pt-2 mt-1">
              <Link to="/login" onClick={() => setMenuOpen(false)}
                className="flex items-center justify-center gap-2 w-full px-3 py-3 rounded-xl bg-green-500 hover:bg-green-400 text-black transition-colors text-sm font-black">
                Entrar na conta
              </Link>
            </div>
          </div>
        )}
      </nav>

      <section className="relative overflow-hidden">
        {/* Troféu no fundo */}
        <img src="/trofeu.png" alt="" aria-hidden="true"
          className="absolute right-0 top-0 h-full max-w-[55%] object-contain object-right opacity-[0.07] pointer-events-none select-none hidden md:block"
          onError={e => (e.currentTarget.style.display = 'none')} />
        {/* Background gradients */}
        <div className="absolute inset-0 bg-gradient-to-br from-green-500/6 via-transparent to-transparent" />

        <div className="max-w-5xl mx-auto px-4 pt-20 pb-24 relative">
          <div className="grid md:grid-cols-2 gap-12 items-start">

            {/* Texto */}
            <div>
              {/* Badge AO VIVO */}
              <div className="inline-flex items-center gap-2 mb-6">
                <Trophy className="w-6 h-6 text-yellow-400" />
                <span className="bg-yellow-400/10 border border-yellow-400/30 text-yellow-400 text-xs font-semibold px-3 py-1 rounded-full inline-flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 bg-yellow-400 rounded-full animate-pulse" />
                  Brasileirão e Premier League ao vivo
                </span>
              </div>

              <h1 className="text-4xl md:text-5xl font-black leading-[1.1] mb-5 tracking-tight">
                Picks de futebol
                <br />
                <span className="text-green-500">gerados por IA,</span>
                <br />
                entregues todo dia.
              </h1>

              <p className="text-zinc-400 text-base leading-relaxed mb-8">
                A IA analisa cada jogo do Brasileirão e da Premier League com dados reais de
                estatísticas, forma recente e odds de mercado. Você recebe os melhores picks com edge positivo
                toda manhã. De graça pra começar.
              </p>

              <div className="flex flex-col sm:flex-row gap-3 mb-8">
                <Link to="/login?mode=register"
                  className="bg-green-500 hover:bg-green-400 text-black font-black px-7 py-3.5 rounded-xl text-sm transition-colors text-center">
                  Criar conta · 2 dias VIP grátis
                </Link>
                <a href="#resultados"
                  className="border border-zinc-700 hover:border-zinc-500 text-zinc-300 hover:text-white font-semibold px-7 py-3.5 rounded-xl text-sm transition-colors text-center">
                  Ver resultados reais
                </a>
              </div>

              <SocialProofStats />
            </div>

            {/* Engine rodando ao vivo + Dica do Dia real -- preenche a coluna,
                nao mockado. So desktop; no mobile o FreePickTeaser (secao cheia
                logo abaixo do hero) cobre o mesmo conteudo pra quem acessa
                por Android/Safari web. */}
            <div className="hidden md:flex md:flex-col md:gap-6">
              <div className="relative">
                <div className="absolute -inset-4 bg-gradient-to-br from-green-500/10 to-yellow-400/10 rounded-3xl blur-xl" />
                <div className="relative">
                  <BastidoresAnimation />
                </div>
              </div>
              <FreePickTeaserCard />
            </div>
          </div>
        </div>
      </section>

      <FreePickTeaser />

      <ActivityTicker />

      <ActiveLeagues />

      <ThreeSteps />

      <RecentResults />

      <LeaderboardTeaser />

      <section className="py-24">
        <div className="max-w-5xl mx-auto px-4">
          <div className="grid md:grid-cols-2 gap-16 items-center">
            {/* Texto */}
            <div>
              <h2 className="text-3xl md:text-4xl font-black mb-5 leading-tight">
                Converse com uma IA<br />
                <span className="text-green-500">especialista em futebol</span>
              </h2>
              <p className="text-zinc-400 text-sm leading-relaxed mb-6">
                Diferente de outras IAs genéricas, o nosso agente é treinado 100% no contexto de apostas esportivas.
                Pergunte sobre qualquer jogo, seleção, mercado ou estratégia e receba análises com base nos dados reais do sistema.
              </p>
              <ul className="space-y-3 mb-8">
                {[
                  'Analisa picks do dia sob demanda',
                  'Explica cada mercado e odd recomendada',
                  'Compara times com estatísticas reais',
                  'Sugere estratégias de gestão de banca',
                  'Disponível 24/7, resposta em segundos',
                ].map(t => (
                  <li key={t} className="flex items-center gap-3 text-sm text-zinc-300">
                    <Check />
                    {t}
                  </li>
                ))}
              </ul>
              <Link to="/login?mode=register" className="inline-block bg-green-500/10 border border-green-500/30 hover:bg-green-500/20 text-green-400 font-bold px-6 py-3 rounded-xl text-sm transition-colors">
                Experimentar o agente IA
              </Link>
            </div>

            {/* Demo chat */}
            <div className="bg-zinc-950 border border-zinc-800 rounded-2xl overflow-hidden">
              <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                  <span className="text-sm font-black text-white">Agente PickIA</span>
                </div>
                <span className="text-xs text-zinc-500 bg-zinc-800 px-2 py-0.5 rounded">Futebol · IA</span>
              </div>
              <div className="p-4 space-y-3 min-h-[260px]">
                <div className="flex justify-end">
                  <div className="bg-green-600 text-white text-sm px-4 py-2.5 rounded-2xl rounded-tr-sm max-w-[80%]">
                    {chatMessages[chatDemo].q}
                  </div>
                </div>
                <div className="flex items-start gap-2">
                  <div className="w-7 h-7 bg-zinc-800 border border-zinc-700 rounded-full flex items-center justify-center shrink-0 mt-0.5">
                    <svg className="w-4 h-4 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17H3a2 2 0 01-2-2V5a2 2 0 012-2h14a2 2 0 012 2v10a2 2 0 01-2 2h-2" />
                    </svg>
                  </div>
                  <div className="bg-zinc-900 border border-zinc-800 text-zinc-300 text-sm px-4 py-2.5 rounded-2xl rounded-tl-sm max-w-[85%] leading-relaxed">
                    {chatMessages[chatDemo].a}
                  </div>
                </div>
              </div>
              <div className="px-4 pb-4">
                <div className="bg-zinc-900 border border-zinc-700 rounded-xl px-3 py-2.5 flex items-center gap-2">
                  <span className="text-zinc-600 text-sm flex-1">Pergunte sobre qualquer jogo...</span>
                  <div className="w-7 h-7 bg-green-600 rounded-lg flex items-center justify-center">
                    <svg className="w-3.5 h-3.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                    </svg>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="planos" className="py-24">
        <div className="max-w-4xl mx-auto px-4">
          <div className="text-center mb-12">
            <h2 className="text-3xl font-black mb-3">Comece de graça, evolua quando quiser</h2>
            <p className="text-zinc-400 text-sm max-w-md mx-auto">
              Teste 2 dias com acesso VIP completo. Depois escolha seu plano.
            </p>
          </div>

          <div className="grid md:grid-cols-3 gap-5">
            {/* Free */}
            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-7">
              <span className="inline-block text-xs text-zinc-400 font-semibold bg-zinc-800 px-2.5 py-1 rounded-lg mb-3">Free</span>
              <p className="text-3xl font-black text-white mb-0.5">R$ 0</p>
              <p className="text-zinc-500 text-xs mb-6">Para sempre</p>
              <div className="space-y-2.5 mb-8">
                {[
                  [true,  '1 pick gratuito por dia'],
                  [true,  'Histórico do Pick Free'],
                  [true,  'Resultados de todos os picks'],
                  [true,  'Detalhes de picks resolvidos'],
                  [false, 'Picks VIP (10–20/dia)'],
                  [false, 'Múltiplas geradas por IA'],
                  [false, 'Alavancagem'],
                  [false, 'Agente IA de futebol'],
                ].map(([ok, t]) => (
                  <div key={t as string} className="flex items-center gap-2.5">
                    {ok ? <Check /> : <X />}
                    <span className={`text-sm ${ok ? 'text-zinc-200' : 'text-zinc-600'}`}>{t as string}</span>
                  </div>
                ))}
              </div>
              <Link to="/login?mode=register" className="block text-center border border-zinc-700 hover:border-zinc-500 text-zinc-400 hover:text-white font-bold py-2.5 rounded-xl text-sm transition-colors">
                Criar conta grátis
              </Link>
            </div>

            {/* Trial · destaque */}
            <div className="relative bg-zinc-900 border border-green-500/50 rounded-2xl p-7 overflow-hidden">
              <div className="absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-transparent via-green-500 to-transparent" />
              <div className="absolute top-3.5 right-4">
                <span className="bg-green-500 text-black text-[10px] font-black px-2.5 py-1 rounded-full uppercase tracking-wider">
                  Começar agora
                </span>
              </div>
              <span className="inline-block text-xs text-green-400 font-semibold bg-green-500/10 border border-green-500/20 px-2.5 py-1 rounded-lg mb-3">Teste grátis</span>
              <p className="text-3xl font-black text-white mb-0.5">R$ 0</p>
              <p className="text-zinc-400 text-xs mb-6">2 dias completos · Sem compromisso</p>
              <div className="space-y-2.5 mb-8">
                {[
                  'Pick Free + todos os Picks VIP',
                  'Múltiplas geradas pela IA',
                  'Alavancagem',
                  'Agente IA de futebol',
                  'Histórico completo com filtros',
                  'Análise estatística de cada jogo',
                  'Comunidade VIP exclusiva',
                  'Após 2 dias: Free automaticamente',
                ].map(t => (
                  <div key={t} className="flex items-center gap-2.5">
                    <Check />
                    <span className="text-sm text-zinc-200">{t}</span>
                  </div>
                ))}
              </div>
              <Link to="/login?mode=register" className="block text-center bg-green-500 hover:bg-green-400 text-black font-black py-2.5 rounded-xl text-sm transition-colors">
                Ativar teste gratuito
              </Link>
            </div>

            {/* VIP */}
            <div className="bg-zinc-900 border border-yellow-400/30 rounded-2xl p-7 overflow-hidden relative">
              <div className="absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-transparent via-yellow-400/60 to-transparent" />
              <span className="inline-block text-xs text-yellow-400 font-semibold bg-yellow-400/10 border border-yellow-400/20 px-2.5 py-1 rounded-lg mb-3">VIP</span>
              <p className="text-3xl font-black text-white mb-0.5">R$ 39,90<span className="text-base font-semibold text-zinc-500">/mês</span></p>
              <p className="text-zinc-500 text-xs mb-1">Menos de R$1,33 por dia</p>
              <p className="text-zinc-600 text-[10px] mb-6">Menos que uma aposta perdida</p>
              <div className="space-y-2.5 mb-8">
                {[
                  'Tudo do Teste VIP',
                  'Acesso permanente sem expiração',
                  'Sem limite de período',
                  'Suporte prioritário',
                  'Brasileirão Série A e B completos',
                  'Premier League completa',
                ].map(t => (
                  <div key={t} className="flex items-center gap-2.5">
                    <Check />
                    <span className="text-sm text-zinc-200">{t}</span>
                  </div>
                ))}
              </div>
              <Link to="/planos" className="block text-center bg-yellow-400/10 border border-yellow-400/30 hover:bg-yellow-400/20 text-yellow-400 font-black py-2.5 rounded-xl text-sm transition-colors">
                Ver planos VIP
              </Link>
            </div>
          </div>
        </div>
      </section>

      <section className="py-16 bg-black border-t border-zinc-800/60">
        <div className="max-w-3xl mx-auto px-4">
          <div className="bg-zinc-900 border border-green-500/20 rounded-2xl p-8 text-center">
            <div className="inline-flex items-center justify-center w-12 h-12 bg-green-500/10 border border-green-500/30 rounded-2xl mb-4">
              <UserPlus className="w-6 h-6 text-green-500" />
            </div>
            <h2 className="text-2xl font-black text-white mb-2">Indique e ganhe dias de VIP grátis</h2>
            <p className="text-zinc-400 text-sm max-w-md mx-auto mb-6">
              Cada amigo que criar conta pela sua indicação te dá +1 dia de VIP. Se ele virar assinante,
              você ganha +2 dias extras. Sem limite de indicações.
            </p>
            <Link to="/login?mode=register" className="inline-flex items-center gap-2 bg-green-500 hover:bg-green-400 text-black font-black px-7 py-3 rounded-xl text-sm transition-colors">
              Criar conta e começar a indicar
            </Link>
          </div>
        </div>
      </section>

      <section className="py-24 bg-zinc-950 border-y border-zinc-800/60">
        <div className="max-w-3xl mx-auto px-4">
          <div className="text-center mb-12">
            <h2 className="text-3xl font-black">Dúvidas frequentes</h2>
          </div>
          <div className="space-y-3">
            {[
              {
                q: 'Quando os picks do dia ficam disponíveis?',
                a: 'Os picks são gerados automaticamente toda manhã. Acesse /picks após as 9h e eles já estarão lá. Em dias de muitos jogos pode levar alguns minutos a mais.',
              },
              {
                q: 'Posso cancelar quando quiser?',
                a: 'Sim. Você pode solicitar o cancelamento a qualquer momento via WhatsApp. Pelo Código de Defesa do Consumidor, compras digitais têm 7 dias de direito de arrependimento com reembolso total.',
              },
              {
                q: 'O que é o trial gratuito de 2 dias?',
                a: 'Ao criar sua conta você ganha 2 dias de acesso VIP completo. Após os 2 dias o acesso vira Free automaticamente. Só é ativado uma vez por conta.',
              },
              {
                q: 'Os picks são garantidos?',
                a: 'Não. Nenhum pick em apostas esportivas é garantido. A IA analisa dados estatísticos e encontra apostas com valor esperado positivo (EV+), mas resultados passados não garantem resultados futuros. Aposte com responsabilidade.',
              },
              {
                q: 'O que é a Alavancagem?',
                a: 'Uma estratégia que começa com um valor fixo (ex: R$50) e reinveste 100% do lucro a cada GREEN. Uma sequência de 5 acertos pode multiplicar o valor várias vezes. Em caso de RED, recomeça do início.',
              },
              {
                q: 'Funciona no celular (iPhone e Android)?',
                a: 'Sim, o site foi desenvolvido para funcionar perfeitamente em todos os dispositivos. Você pode inclusive salvar na tela inicial do seu celular para acesso rápido como um app.',
              },
              {
                q: 'Quais ligas são cobertas?',
                a: 'Brasileirão Série A e B e Premier League estão ao vivo agora. A cobertura entra automaticamente assim que a temporada de cada liga estiver rolando. Mais ligas e torneios entram conforme o calendário avança.',
              },
            ].map(({ q, a }, i) => (
              <div key={i} className="border border-zinc-800 rounded-xl overflow-hidden">
                <button
                  onClick={() => setOpenFaq(openFaq === i ? null : i)}
                  className="w-full flex items-center justify-between gap-4 px-5 py-4 text-left font-semibold text-white text-sm hover:bg-zinc-900 transition-colors"
                >
                  {q}
                  <span className={`text-zinc-500 text-lg font-light shrink-0 leading-none transition-transform duration-200 ${openFaq === i ? 'rotate-45' : ''}`}>+</span>
                </button>
                {openFaq === i && (
                  <p className="px-5 pb-5 pt-3 text-zinc-400 text-sm leading-relaxed border-t border-zinc-800/60">{a}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="py-24 border-t border-zinc-800/60 relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-green-500/5 via-transparent to-yellow-400/5" />
        <div className="absolute top-0 inset-x-0 h-px bg-gradient-to-r from-transparent via-green-500/40 to-transparent" />
        <div className="max-w-2xl mx-auto px-4 text-center relative">
          <div className="flex items-center justify-center gap-3 mb-6">
            <Trophy className="w-9 h-9 text-yellow-400" />
          </div>
          <div className="inline-flex items-center gap-1.5 bg-yellow-400/10 border border-yellow-400/30 text-yellow-400 text-xs font-semibold px-3 py-1 rounded-full mb-6">
            <span className="w-1.5 h-1.5 bg-yellow-400 rounded-full animate-pulse" />
            Brasileirão e Premier League ao vivo
          </div>
          <h2 className="text-3xl md:text-4xl font-black mb-4 leading-tight">
            Todo round tem valor.<br /><span className="text-green-500">Não fique de fora.</span>
          </h2>
          <p className="text-zinc-400 text-sm mb-8 leading-relaxed">
            Crie sua conta e ganhe <span className="text-white font-bold">2 dias de acesso VIP completo.</span>
            {' '}Picks de Brasileirão, Premier League, agente IA e muito mais.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link to="/login?mode=register"
              className="bg-green-500 hover:bg-green-400 text-black font-black px-8 py-4 rounded-xl text-sm transition-colors w-full sm:w-auto">
              Criar conta · 2 dias VIP grátis
            </Link>
            <a href="#resultados"
              className="border border-zinc-700 hover:border-zinc-500 text-zinc-300 hover:text-white font-semibold px-8 py-4 rounded-xl text-sm transition-colors w-full sm:w-auto text-center">
              Ver resultados primeiro
            </a>
          </div>
          <p className="text-xs text-zinc-600 mt-4">Sem compromisso · Após 2 dias vira Free automaticamente</p>
        </div>
      </section>

      <Footer />

      <StickyMobileCTA />

    </div>
    </>
  )
}
