import { useEffect, useState } from 'react'
import { Spinner } from '../components/ui'
import { useParams, useSearchParams, Link } from 'react-router-dom'
import { Helmet } from 'react-helmet-async'
import { Lock, Crown, TrendingUp } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import api from '../services/api'
import { getResultStyle, PICK_TYPE_LABEL } from '../utils/resultStyle'
import { TeamLogo, LeagueLogo } from '../components/TeamLogo'

export default function PickPublico() {
  const { pick_type, pick_id } = useParams<{ pick_type: string; pick_id: string }>()
  const [searchParams] = useSearchParams()
  const refCode = searchParams.get('ref') ?? ''
  const { user } = useAuth()

  const [pick, setPick]     = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)

  // Se VIP, carrega detalhes completos
  const [fullPick, setFullPick] = useState<any>(null)
  const isVip = user && (user.plan === 'vip' || user.plan === 'admin' || user.plan === 'trial')

  useEffect(() => {
    if (!pick_type || !pick_id) return
    api.get(`/public/pick/${pick_type}/${pick_id}`)
      .then(r => setPick(r.data))
      .catch(() => setNotFound(true))
      .finally(() => setLoading(false))
  }, [pick_type, pick_id])

  /*
   * Detalhe do pick pro assinante VIP que abriu um link compartilhado.
   *
   * Chamava `/suggestions/{pick_type}/{pick_id}`, rota que NUNCA existiu no
   * backend -- o 404 caia no .catch vazio e `fullPick` ficava null pra
   * sempre. Efeito: o proprio assinante VIP via o bloco borrado de "Disponivel
   * apenas para assinantes VIP" na pagina que ele mesmo compartilhou.
   * Encontrado em 2026-08-14 cruzando as chamadas do front com as rotas
   * registradas.
   *
   * A rota certa e' a mesma que o painel de detalhe ja usa, com o tipo indo
   * por query em vez de caminho.
   */
  useEffect(() => {
    if (!isVip || !pick_type || !pick_id) return
    api.get(`/suggestions/${pick_id}/detail`, { params: { pick_type } })
      .then(r => setFullPick(r.data?.suggestion ?? null))
      .catch(() => {})
  }, [isVip, pick_type, pick_id])

  const signupUrl = `/login?ref=${refCode}&redirect=/p/${pick_type}/${pick_id}`

  if (loading) {
    return (
      <div className="min-h-screen bg-surface-0 flex items-center justify-center">
        <Spinner size="lg" />
      </div>
    )
  }

  if (notFound || !pick) {
    return (
      <div className="min-h-screen bg-surface-0 flex flex-col items-center justify-center p-6 text-center">
        <p className="text-ink-2 text-lg font-semibold mb-2">Pick não encontrado</p>
        <p className="text-ink-4 text-sm mb-6">O link pode ter expirado ou sido removido.</p>
        <Link
          to="/"
          className="inline-flex items-center justify-center text-sm font-bold text-accent-ink bg-accent/10 border border-accent/30 hover:bg-accent/20 rounded-md px-5 py-2.5 min-h-[40px] transition-colors"
        >
          Ir para o Pick IA
        </Link>
      </div>
    )
  }

  const rs = getResultStyle(pick.result)
  const profit = pick.profit != null ? Number(pick.profit) : null
  const odd    = pick.odd != null ? Number(pick.odd) : null
  const typeLabel = PICK_TYPE_LABEL[pick.pick_type ?? pick_type ?? 'vip'] ?? 'VIP'
  const resultLabel = pick.result ? ` · ${pick.result}` : ''
  const pageTitle = `${pick.home_team_name ?? pick.teams_preview?.[0] ?? 'Múltipla'}${pick.away_team_name ? ` x ${pick.away_team_name}` : ''}${resultLabel} · Pick IA`

  return (
    <div className="min-h-screen bg-surface-0 flex flex-col">
      <Helmet>
        <title>{pageTitle}</title>
        <meta name="description" content={`Odd ${odd?.toFixed(2) ?? '-'} · ${typeLabel} · Análise de IA para apostas esportivas.`} />
      </Helmet>
      {/* Topo */}
      <div className="px-4 pt-5 pb-3 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-1.5">
          <span className="text-ink-1 font-black text-lg tracking-tight">Pick<span className="text-green-400">IA</span></span>
        </Link>
        {user ? (
          <Link to="/picks" className="text-xs text-ink-2 hover:text-ink-1 transition-colors">Ver meus picks</Link>
        ) : (
          <Link to={signupUrl} className="text-xs font-bold text-green-400 hover:text-green-300 transition-colors">Entrar</Link>
        )}
      </div>

      {/* Card principal */}
      <div className="flex-1 px-4 py-4 max-w-lg mx-auto w-full">
        <div className="bg-surface-0 border border-line rounded-lg overflow-hidden">

          {/* Accent bar */}
          <div className={`h-0.5 bg-gradient-to-r from-transparent via-green-500 to-transparent ${pick.result === 'RED' ? 'via-red-500' : ''}`} />

          {/* Header: tipo + resultado */}
          <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-line/60">
            <div className="flex items-center gap-2">
              <Crown className="w-3.5 h-3.5 text-yellow-400" />
              <span className="text-xs font-black text-yellow-400">{typeLabel}</span>
              {pick.league_name && (
                <div className="flex items-center gap-1">
                  <LeagueLogo id={pick.league_id} name={pick.league_name} />
                  <span className="text-[10px] text-ink-4 truncate max-w-[90px]">{pick.league_name}</span>
                </div>
              )}
            </div>
            {rs ? (
              <span className={`text-xs font-black px-3 py-1 rounded-lg border ${rs.bg} ${rs.border} ${rs.text}`}>
                {rs.label}
              </span>
            ) : (
              <span className="text-[10px] text-ink-3 border border-line px-2 py-1 rounded-lg">Pendente</span>
            )}
          </div>

          {/* Times */}
          <div className="px-5 py-4 border-b border-line/60">
            {pick.pick_type === 'multipla' && pick.teams_preview ? (
              <div className="space-y-1.5">
                {pick.teams_preview.map((t: string, i: number) => (
                  <p key={i} className="text-sm font-semibold text-ink-1">{t}</p>
                ))}
              </div>
            ) : (
              <div className="flex items-center gap-3">
                <TeamLogo id={pick.home_team_id} name={pick.home_team_name ?? ''} size={28} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-bold text-ink-1 truncate">{pick.home_team_name}</p>
                  <p className="text-[11px] text-ink-3">vs</p>
                  <p className="text-sm font-bold text-ink-1 truncate">{pick.away_team_name}</p>
                </div>
                <TeamLogo id={pick.away_team_id} name={pick.away_team_name ?? ''} size={28} />
              </div>
            )}
            {pick.match_date && (
              <p className="text-[10px] text-ink-4 mt-2">
                {new Date(pick.match_date + (pick.match_date.length === 10 ? 'T12:00:00' : '')).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short', year: 'numeric' })}
              </p>
            )}
          </div>

          {/* Métricas: odd + lucro */}
          <div className="flex divide-x divide-line/60 border-b border-line/60">
            <div className="flex-1 px-4 py-3 text-center">
              <p className="text-[10px] text-ink-3 mb-0.5">Odd</p>
              <p className="font-mono text-2xl font-black text-green-400">{odd?.toFixed(2) ?? '-'}</p>
            </div>
            {profit != null ? (
              <div className="flex-1 px-4 py-3 text-center">
                <p className="text-[10px] text-ink-3 mb-0.5">Lucro</p>
                <p className={`font-mono text-2xl font-black ${profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {profit >= 0 ? '+' : ''}{profit.toFixed(2)}u
                </p>
              </div>
            ) : (
              <div className="flex-1 px-4 py-3 text-center">
                <p className="text-[10px] text-ink-3 mb-0.5">Lucro pot.</p>
                <p className="font-mono text-2xl font-black text-ink-2">
                  {odd ? `+${(odd - 1).toFixed(2)}u` : '-'}
                </p>
              </div>
            )}
          </div>

          {/* Detalhes do pick: bloqueado ou visivel (VIP) */}
          {isVip && fullPick ? (
            <div className="px-5 py-4 space-y-2 border-b border-line/60">
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-ink-3">Mercado</span>
                <span className="text-sm font-bold text-ink-1">{fullPick.market} {fullPick.line ? `· ${fullPick.line}` : ''}</span>
              </div>
              {fullPick.reasoning && (
                <p className="text-xs text-ink-2 leading-relaxed line-clamp-4">{fullPick.reasoning}</p>
              )}
            </div>
          ) : (
            <div className="px-5 py-4 border-b border-line/60">
              <div className="flex items-center gap-3 px-4 py-3 bg-surface-1 border border-line rounded-md">
                <Lock className="w-4 h-4 text-yellow-400 shrink-0" />
                <div>
                  <p className="text-xs font-bold text-ink-1">Mercado · Linha · Análise da IA</p>
                  <p className="text-[11px] text-ink-3 mt-0.5">Disponível apenas para assinantes VIP</p>
                </div>
              </div>
              <div className="mt-2 space-y-1.5">
                {['Mercado: ████████████', 'Linha: ██████', 'Análise da IA...'].map((t, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <div className="h-3 bg-surface-2 rounded-sm flex-1 opacity-40 select-none blur-[2px]">
                      <span className="text-[10px] text-ink-4 px-2">{t}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* CTA */}
          {!isVip && (
            <div className="px-5 py-5 space-y-3">
              <p className="text-center text-xs text-ink-2 leading-relaxed">
                {rs && rs.label === 'GREEN'
                  ? 'A IA acertou esse pick. Quer receber os próximos antes do jogo?'
                  : 'Receba picks analisados por IA todos os dias, antes das partidas.'}
              </p>
              <Link
                to={signupUrl}
                className="flex items-center justify-center gap-2 w-full py-3.5 rounded-md bg-green-600 hover:bg-green-500 text-white font-black text-sm transition-colors"
              >
                <TrendingUp className="w-4 h-4" />
                {user ? 'Assinar VIP' : 'Criar conta gratuita e assinar VIP'}
              </Link>
              {!user && (
                <p className="text-center text-[10px] text-ink-4">
                  2 dias de VIP grátis no cadastro
                </p>
              )}
            </div>
          )}

          {isVip && (
            <div className="px-5 py-4 text-center">
              <Link to="/picks" className="text-sm text-green-400 hover:text-green-300 font-semibold transition-colors">
                Ver todos os picks de hoje
              </Link>
            </div>
          )}
        </div>

        {/* Footer branding */}
        <p className="text-center text-[10px] text-ink-4 mt-6">Pick IA · Tips por Inteligência Artificial</p>
      </div>
    </div>
  )
}
