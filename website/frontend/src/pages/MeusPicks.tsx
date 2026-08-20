import { useEffect, useState, useCallback } from 'react'
import { PillGroup, Spinner } from '../components/ui'
import { PERIODOS, PERIODO_PADRAO, dentroDoPeriodo, type PeriodoKey } from '../lib/periodo'
import { ChevronLeft, ChevronRight, Trash2, RotateCcw, BarChart3 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { tabFade, toastUp } from '../lib/motion'
import api from '../services/api'
import PageShell from '../components/PageShell'
import { translateMarket, explainMarket } from '../utils/marketTranslate'
import SuggestionDetail from '../components/SuggestionDetail'
import ProfitChart from '../components/ProfitChart'
import { fmtBRL, fmtSigned, winRate as calcWinRate } from '../utils/format'
import { getResultStyle, PICK_TYPE_CLS } from '../utils/resultStyle'
import { TeamLogo } from '../components/TeamLogo'
import InfoTip from '../components/InfoTip'
import ResetMonthModal from '../components/ResetMonthModal'

const SOURCE_LBL: Record<string, string> = {
  vip: 'VIP', free: 'Free', multipla: 'Múlt.', alavancagem: 'Alav.',
  faltas: 'Faltas', goleiros: 'Defesas',
}

const pnlColor = (v: number | null) =>
  v == null ? 'text-ink-4' : v > 0 ? 'text-green-500' : v < 0 ? 'text-red-400' : 'text-ink-2'

export default function MeusPicks() {
  const navigate = useNavigate()

  const [data,       setData]       = useState<any>(null)
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState(false)
  const [tab,        setTab]        = useState<'pendentes' | 'resolvidos'>('pendentes')
  const [dayOffset,  setDayOffset]  = useState(0)
  const [detailPick,   setDetailPick]   = useState<{ id: number; pick_type: string } | null>(null)
  const [showRemoved,  setShowRemoved]  = useState(false)
  const [autoSwitched, setAutoSwitched] = useState(false)
  const [loadingMore,  setLoadingMore]  = useState(false)
  const load = useCallback(() => {
    setLoading(true)
    setError(false)
    api.get('/banca')
      .then(r => setData(r.data))
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [])

  /*
   * Zerar o mês mora AQUI, e não na Banca.
   *
   * O que o comando apaga é `user_followed_picks` · exatamente a lista que
   * esta tela mostra. Se deleta onde se vê. Na Banca o botão ficava sobre uma
   * página que, depois de zerar, não tem mais nada para exibir: gráfico sem
   * série, sequência vazia, distribuição zerada.
   *
   * O resumo vem de /banca/monthly-close com o mês atual, não de contar as
   * linhas da tela: a lista respeita o filtro de período escolhido e o comando
   * do servidor não. Contando aqui, o aviso prometeria um número e o backend
   * apagaria outro.
   */
  const [showReset, setShowReset] = useState(false)
  const [mesAtual, setMesAtual] = useState<{ label: string; apostas: number; pnl: number } | null>(null)

  const carregarMesAtual = useCallback(() => {
    const agora = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' }).slice(0, 7)
    api.get('/banca/monthly-close', { params: { month: agora } })
      .then(r => setMesAtual({
        label: r.data?.month_label ?? 'este mês',
        apostas: Number(r.data?.total_followed ?? 0),
        pnl: Number(r.data?.total_pnl ?? 0),
      }))
      .catch(() => setMesAtual(null))
  }, [])

  useEffect(() => { carregarMesAtual() }, [carregarMesAtual])

  const zerarMes = async () => {
    await api.post('/banca/reset-month')
    setShowReset(false)
    carregarMesAtual()
    load()
  }

  const loadMoreResolved = () => {
    if (loadingMore || !data?.has_more_resolved) return
    setLoadingMore(true)
    const resolvedLoaded = (data.entries ?? []).filter((e: any) => e.result).length
    api.get('/banca', { params: { resolved_offset: resolvedLoaded } })
      .then(r => setData((prev: any) => {
        if (!prev) return r.data
        const existingIds = new Set(prev.entries.map((e: any) => e.id))
        const merged = [...prev.entries, ...r.data.entries.filter((e: any) => !existingIds.has(e.id))]
        return { ...prev, entries: merged, has_more_resolved: r.data.has_more_resolved }
      }))
      .catch(() => {})
      .finally(() => setLoadingMore(false))
  }

  useEffect(() => { load() }, [load])

  // Auto-muda para Resolvidos na 1ª carga se não houver pendentes
  useEffect(() => {
    if (data && !autoSwitched) {
      setAutoSwitched(true)
      const pend = (data.entries ?? []).filter((e: any) => !e.result)
      if (pend.length === 0) setTab('resolvidos')
    }
  }, [data])

  const handleUnfollow = async (pick_id: number, pick_type: string) => {
    try {
      await api.delete(`/banca/follow/${pick_id}/${pick_type}`)
      load()
      setShowRemoved(true)
      setTimeout(() => setShowRemoved(false), 3000)
    } catch { /* silently ignore */ }
  }

  const [daysBack, setDaysBack] = useState<PeriodoKey>(PERIODO_PADRAO)
  const [todayPage, setTodayPage] = useState(0)
  const PAGE_SIZE = 15

  const changeTab = (t: 'pendentes' | 'resolvidos') => {
    setTab(t)
    setDayOffset(0)
    setDaysBack(PERIODO_PADRAO)
    setTodayPage(0)
  }



  const allEntries: any[] = data?.entries ?? []
  const pendentes  = allEntries.filter(e => !e.result)
  // Resolvidos: mais recente primeiro
  const resolvidos = allEntries
    .filter(e => e.result)
    .sort((a, b) => new Date(b.followed_at ?? 0).getTime() - new Date(a.followed_at ?? 0).getTime())
  const tabEntries = tab === 'pendentes' ? pendentes : resolvidos

  const todayKey     = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })
  const yesterdayKey = new Date(Date.now() - 86400000).toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })

  const dayLabel = (key: string) =>
    key === todayKey     ? 'Hoje'
    : key === yesterdayKey ? 'Ontem'
    : new Date(key + 'T12:00:00').toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: 'long' })

  // Entradas filtradas pelo período selecionado (para stats + lista)
  const filteredByPeriod = daysBack === 'tudo'
    ? allEntries
    : allEntries.filter((e: any) => {
        if (!e.followed_at) return false
        const dia = new Date(e.followed_at).toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })
        return dentroDoPeriodo(dia, daysBack)
      })

  const filteredTabEntries = daysBack === 'tudo' ? tabEntries : filteredByPeriod.filter((e: any) =>
    tab === 'pendentes' ? !e.result : !!e.result
  )

  // Navegação por dia dentro do filtro
  const uniqueDatesFiltered = Array.from(new Set(
    filteredTabEntries.map((e: any) =>
      e.followed_at
        ? new Date(e.followed_at).toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })
        : null
    ).filter(Boolean)
  )).sort((a, b) => (b as string).localeCompare(a as string)) as string[]

  const clampedOffset = Math.min(dayOffset, Math.max(0, uniqueDatesFiltered.length - 1))
  const selectedKey   = uniqueDatesFiltered[clampedOffset] ?? todayKey
  const pageItems     = daysBack === 'tudo'
    ? filteredTabEntries  // Hoje: mostra tudo sem separar por dia
    : filteredTabEntries.filter((e: any) =>
        e.followed_at &&
        new Date(e.followed_at).toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' }) === selectedKey
      )
  const hasPrev = clampedOffset < uniqueDatesFiltered.length - 1
  const hasNext = clampedOffset > 0

  const displayItems = daysBack === 'tudo'
    ? pageItems.slice(todayPage * PAGE_SIZE, (todayPage + 1) * PAGE_SIZE)
    : pageItems

  return (
    <PageShell
      title="Meus Picks"
      description="Suas apostas pendentes e resolvidas, com resultado e saldo de cada uma."
      noindex
      width="full"
      bar={{
        back: true,
        title: 'Meus Picks',
        sub: 'Suas apostas pendentes e resolvidas',
        /*
         * Aparece pra quem tem aposta registrada, mesmo que nenhuma seja do
         * mês corrente · nesse caso vem desabilitado, dizendo por quê.
         *
         * A regra anterior escondia o botão quando o mês estava vazio, e isso
         * dava um efeito perverso: logo depois de zerar, que é justamente
         * quando se volta pra conferir se funcionou, ele sumia. Controle que
         * desaparece sem explicação confunde mais do que controle desabilitado
         * que diz o motivo.
         *
         * Some de vez só pra quem nunca registrou nada: aí não é falta de
         * explicação, é função que ainda não faz sentido existir.
         *
         * No celular some o ÍCONE, nunca o texto: seta circular sozinha lê
         * como "recarregar", e ambiguidade dessas num botão sem volta é
         * armadilha. O clique aqui só ABRE o aviso · nada é apagado nele.
         */
        actions: (data?.entries?.length ?? 0) > 0 ? (
          <>
          {/* Quebra por pipeline · a página responde "ganhei com o quê", que é
              a pergunta que esta tela não respondia. Fica ao lado de "Zerar
              mês" por ser a outra coisa que se faz com esta lista inteira. */}
          <button
            onClick={() => navigate('/meus-picks/pipelines')}
            title="Ver quanto cada pipeline rendeu na sua banca"
            className="flex items-center gap-1.5 text-xs font-semibold text-ink-3 hover:text-ink-1 border border-line-strong hover:border-ink-4/40 px-3 py-2 rounded-md transition-colors shrink-0 min-h-[36px]"
          >
            <BarChart3 className="w-3.5 h-3.5 shrink-0 hidden sm:block" />
            Por pipeline
          </button>
          <button
            onClick={() => setShowReset(true)}
            disabled={(mesAtual?.apostas ?? 0) === 0}
            title={
              (mesAtual?.apostas ?? 0) > 0
                ? `Tirar as ${mesAtual!.apostas} apostas de ${mesAtual!.label} da banca`
                : `Nenhuma aposta registrada em ${mesAtual?.label ?? 'no mês atual'}`
            }
            className="flex items-center gap-1.5 text-xs font-semibold text-ink-3 enabled:hover:text-red-400 border border-line-strong enabled:hover:border-red-500/40 px-3 py-2 rounded-md transition-colors shrink-0 min-h-[36px] disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <RotateCcw className="w-3.5 h-3.5 shrink-0 hidden sm:block" />
            Zerar mês
          </button>
          </>
        ) : undefined,
      }}
    >
      <AnimatePresence>
      {showReset && mesAtual && (
        <ResetMonthModal
          mes={mesAtual.label}
          apostas={mesAtual.apostas}
          pnl={mesAtual.pnl}
          onConfirm={zerarMes}
          onClose={() => setShowReset(false)}
        />
      )}
      </AnimatePresence>
      <AnimatePresence>
      {detailPick && (
        <SuggestionDetail
          id={detailPick.id}
          pickType={detailPick.pick_type}
          onClose={() => setDetailPick(null)}
        />
      )}
      </AnimatePresence>

        {loading ? (
          <div className="card p-16 flex items-center justify-center">
            <Spinner size="lg" />
          </div>
        ) : error ? (
          <div className="card p-10 text-center">
            <p className="text-ink-2 font-semibold mb-1">Erro ao carregar seus picks</p>
            <p className="text-ink-4 text-sm mb-4">Não foi possível conectar ao servidor. Verifique sua conexão.</p>
            <button onClick={load} className="text-sm text-green-400 hover:text-green-300 font-semibold transition-colors">
              Tentar novamente
            </button>
          </div>
        ) : (
          <div className="space-y-4">

            {/* Filtros de período · pills */}
            {/* Mesmo vocabulário e mesma fila da Banca (lib/periodo). As duas
                telas filtram a MESMA lista de apostas e diziam coisas
                diferentes: "Todos" contra "Tudo", "Semana" contra "7 dias", e
                um recorte de 30 dias que só existia lá. */}
            {allEntries.length > 0 && (
              <PillGroup
                options={PERIODOS.map(p => ({ value: p.key, label: p.label }))}
                value={daysBack}
                onChange={v => { setDaysBack(v); setDayOffset(0); setTodayPage(0) }}
              />
            )}

            {/* Resumo · filtra pelo período selecionado */}
            {allEntries.length > 0 && (() => {
              const periodEntries = filteredByPeriod
              const resolved = periodEntries.filter((e: any) => e.result)
              const greenCount = resolved.filter((e: any) => e.result === 'GREEN' || e.result === 'HALF-WIN').length
              const redCount   = resolved.filter((e: any) => e.result === 'RED'   || e.result === 'HALF-LOSS').length
              const pnl = daysBack === 'tudo'
                ? (data?.total_pnl ?? 0)
                : resolved.reduce((acc: number, e: any) => acc + (Number(e.pnl) || 0), 0)
              const wr = calcWinRate(greenCount, resolved.length) ?? 0
              const pnlStr = pnl === 0 ? 'R$ 0' : fmtSigned(pnl)
              return (
                <div className="font-mono grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                  <div className="card p-3 text-center">
                    <div className="text-2xl font-black text-ink-1">{periodEntries.length}</div>
                    <div className="text-[10px] text-ink-3 mt-1">Apostas</div>
                  </div>
                  <div className="card p-3 text-center">
                    <div className={`text-lg sm:text-xl font-black ${pnl > 0 ? 'text-green-500' : pnl < 0 ? 'text-red-400' : 'text-ink-2'}`}>{pnlStr}</div>
                    <div className="text-[10px] text-ink-3 mt-1">
                      {daysBack === 'tudo' ? 'Total' : PERIODOS.find(p => p.key === daysBack)?.label}
                    </div>
                  </div>
                  <div className="card p-3 text-center">
                    <div className={`text-2xl font-black ${wr >= 55 ? 'text-green-500' : 'text-ink-2'}`}>{wr}%</div>
                    <div className="text-[10px] text-ink-3 mt-1">Win rate</div>
                  </div>
                  <div className="card p-3 text-center border-green-500/20">
                    <div className="text-2xl font-black text-green-400">{greenCount}</div>
                    <div className="text-[10px] text-ink-3 mt-1">GREEN</div>
                  </div>
                  <div className="card p-3 text-center border-red-500/20">
                    <div className="text-2xl font-black text-red-400">{redCount}</div>
                    <div className="text-[10px] text-ink-3 mt-1">RED</div>
                  </div>
                </div>
              )
            })()}

            {/* Evolução da banca */}
            {(data?.chart?.length ?? 0) >= 2 && (() => {
              const allChart = (data.chart ?? []).map((p: any, i: number, arr: any[]) => ({
                match_date: p.date,
                profit: i === 0
                  ? p.bankroll - (data?.bankroll_start ?? 100)
                  : p.bankroll - arr[i - 1].bankroll,
              }))
              const chartFiltered = daysBack === 'tudo'
                ? allChart
                : allChart.filter((c: any) => dentroDoPeriodo(c.match_date, daysBack))
              if (chartFiltered.length < 2) return null
              const pnl = data?.total_pnl ?? 0

              /*
               * Leitura do dia a dia, tirada da mesma série do gráfico.
               *
               * A curva mostra para onde foi; estes três números dizem como.
               * Saldo igual pode vir de constância ou de um dia salvando o mês,
               * e a linha sozinha não separa os dois casos.
               */
              const dias = chartFiltered.map((c: any) => Number(c.profit) || 0)
              const positivos = dias.filter((v: number) => v > 0).length
              const melhor = chartFiltered.reduce((a: any, b: any) => (Number(b.profit) > Number(a.profit) ? b : a))
              const pior   = chartFiltered.reduce((a: any, b: any) => (Number(b.profit) < Number(a.profit) ? b : a))
              const diaBR  = (d: string) => `${d.slice(8, 10)}/${d.slice(5, 7)}`

              return (
                <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 items-stretch">
                  <div className="card p-4 xl:col-span-2">
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="text-xs font-semibold text-ink-3">Evolução da Banca</h3>
                      <span className={`text-sm font-black ${pnl >= 0 ? 'text-green-500' : 'text-red-400'}`}>
                        {fmtSigned(pnl)}
                      </span>
                    </div>
                    <ProfitChart data={chartFiltered} unit="R$" height={240} />
                  </div>

                  <div className="card p-4 flex flex-col">
                    <h3 className="text-xs font-semibold text-ink-3 mb-4">Como foi por dia</h3>
                    <dl className="flex flex-col gap-4 flex-1 justify-center">
                      <div>
                        <dd className="font-mono text-2xl font-black text-ink-1">
                          {positivos}<span className="text-ink-4 text-base">/{dias.length}</span>
                        </dd>
                        <dt className="text-[11px] text-ink-3 mt-0.5">Dias no positivo</dt>
                      </div>
                      <div>
                        <dd className="font-mono text-lg font-black text-green-500">
                          {fmtSigned(Number(melhor.profit) || 0)}
                        </dd>
                        <dt className="text-[11px] text-ink-3 mt-0.5">
                          Melhor dia · {diaBR(melhor.match_date)}
                        </dt>
                      </div>
                      <div>
                        <dd className="font-mono text-lg font-black text-red-400">
                          {fmtSigned(Number(pior.profit) || 0)}
                        </dd>
                        <dt className="text-[11px] text-ink-3 mt-0.5">
                          Pior dia · {diaBR(pior.match_date)}
                        </dt>
                      </div>
                    </dl>
                  </div>
                </div>
              )
            })()}

            {/* Tabs */}
            <div className="flex gap-2">
              <motion.button
                whileTap={{ scale: 0.96 }}
                onClick={() => changeTab('pendentes')}
                className={`px-4 py-2 rounded-md text-sm font-bold border transition-colors ${
                  tab === 'pendentes'
                    ? 'bg-yellow-400/10 border-yellow-400/30 text-yellow-400'
                    : 'border-line-strong text-ink-3 hover:border-ink-4 hover:text-ink-2'
                }`}
              >
                Pendentes ({pendentes.length})
              </motion.button>
              <motion.button
                whileTap={{ scale: 0.96 }}
                onClick={() => changeTab('resolvidos')}
                className={`px-4 py-2 rounded-md text-sm font-bold border transition-colors ${
                  tab === 'resolvidos'
                    ? 'bg-green-500/10 border-green-500/30 text-green-400'
                    : 'border-line-strong text-ink-3 hover:border-ink-4 hover:text-ink-2'
                }`}
              >
                Resolvidos ({resolvidos.length})
              </motion.button>
            </div>

            {/* Lista */}
            <AnimatePresence mode="wait">
            <motion.div key={tab} variants={tabFade} initial="hidden" animate="visible" exit="exit">
            {filteredTabEntries.length === 0 ? (
              <div className="card p-12 text-center border-dashed">
                <p className="text-ink-3 text-sm font-semibold mb-2">
                  {tab === 'pendentes' ? 'Nenhuma aposta pendente' : 'Nenhuma aposta resolvida ainda'}
                </p>
                <p className="text-ink-4 text-xs mb-4">
                  Clique em "Apostar" nos picks para registrar suas apostas.
                </p>
                <button onClick={() => navigate('/picks')} className="btn-primary text-sm px-6 py-2.5">
                  Ver picks
                </button>
              </div>
            ) : (
              <>
                {/* Navegação de dia · só aparece quando um filtro de período está ativo */}
                {(typeof daysBack === 'number' ? daysBack > 0 : true) && uniqueDatesFiltered.length > 1 && (
                  <div className="flex items-center justify-between bg-surface-1 border border-line rounded-md px-2 py-2">
                    <button
                      onClick={() => setDayOffset(o => o + 1)}
                      disabled={!hasPrev}
                      className="flex items-center justify-center w-10 h-10 rounded-lg text-ink-3 hover:text-ink-2 hover:bg-surface-2 disabled:opacity-20 transition-colors"
                    >
                      <ChevronLeft className="w-5 h-5" />
                    </button>
                    <div className="text-center">
                      <div className="flex items-center justify-center gap-1.5">
                        <span className="text-sm font-black text-ink-1 capitalize">{dayLabel(selectedKey)}</span>
                        {clampedOffset > 0 && (
                          <button
                            onClick={() => setDayOffset(0)}
                            className="text-[10px] text-green-400 hover:text-green-300 font-bold transition-colors border border-green-500/30 px-1.5 py-0.5 rounded"
                          >
                            Mais recente
                          </button>
                        )}
                      </div>
                      <div className="text-[10px] text-ink-4 mt-0.5">{pageItems.length} pick{pageItems.length !== 1 ? 's' : ''}</div>
                    </div>
                    <button
                      onClick={() => setDayOffset(o => o - 1)}
                      disabled={!hasNext}
                      className="flex items-center justify-center w-10 h-10 rounded-lg text-ink-3 hover:text-ink-2 hover:bg-surface-2 disabled:opacity-20 transition-colors"
                    >
                      <ChevronRight className="w-5 h-5" />
                    </button>
                  </div>
                )}

                {/* Picks do dia */}
                {pageItems.length === 0 ? (
                  <div className="card p-8 text-center border-dashed">
                    <p className="text-ink-4 text-sm">Nenhum pick neste dia.</p>
                  </div>
                ) : (
                  <div className="card overflow-hidden">
                    <div className="divide-y divide-line/60">
                      {displayItems.map((e: any) => {
                        return (
                          <button
                            key={e.id}
                            onClick={() => setDetailPick({ id: e.pick_id, pick_type: e.pick_type })}
                            className="w-full flex items-center gap-3 px-4 py-3 hover:bg-surface-2/40 transition-colors text-left"
                          >
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
                                <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border shrink-0 ${PICK_TYPE_CLS[e.pick_type] ?? ''}`}>
                                  {SOURCE_LBL[e.pick_type] ?? e.pick_type}
                                </span>
                                <TeamLogo id={e.home_team_id} name={e.home_team_name ?? ''} size={16} />
                                <span className="text-sm font-semibold text-ink-1 truncate">
                                  {e.home_team_name
                                    ? e.home_team_name
                                    : e.pick_type === 'multipla'
                                    ? 'Múltipla'
                                    : e.pick_type === 'alavancagem'
                                    ? 'Alavancagem'
                                    : e.market ?? `Pick #${e.pick_id}`}
                                </span>
                                {e.away_team_name && (
                                  <>
                                    <span className="text-ink-4 text-xs shrink-0">vs</span>
                                    <TeamLogo id={e.away_team_id} name={e.away_team_name} size={16} />
                                    <span className="text-sm font-semibold text-ink-1 truncate">{e.away_team_name}</span>
                                  </>
                                )}
                              </div>
                              <div className="flex items-center gap-1 min-w-0">
                                <p className="text-xs text-ink-4 truncate">
                                  {translateMarket(e.market) ?? ''}
                                  {e.line ? ` · ${e.line}` : ''}
                                  {e.actual_odd
                                    ? <> · <span className="text-ink-2">Odd {Number(e.actual_odd).toFixed(2)}</span>{Math.abs(Number(e.actual_odd) - Number(e.odd)) > 0.001 ? <span className="text-ink-4"> (pick: {Number(e.odd).toFixed(2)})</span> : null}</>
                                    : e.odd ? ` · Odd ${Number(e.odd).toFixed(2)}` : ''}
                                </p>
                                <InfoTip text={explainMarket(e.market, e.line)} className="shrink-0" />
                              </div>
                            </div>

                            <div className="flex items-center gap-2 shrink-0">
                              {e.result ? (() => {
                                const rs = getResultStyle(e.result)
                                return (
                                  <span className={`text-xs font-black px-2 py-0.5 rounded-lg border ${rs ? `${rs.bg} ${rs.border} ${rs.text}` : 'text-ink-3'}`}>
                                    {rs ? rs.label : e.result}
                                  </span>
                                )
                              })() : (
                                <span className="text-xs text-yellow-400 bg-yellow-400/10 border border-yellow-400/20 px-2 py-0.5 rounded-lg font-bold">
                                  Pendente
                                </span>
                              )}
                              <span className={`text-sm font-black w-20 text-right ${pnlColor(e.pnl)}`}>
                                {e.pnl != null ? fmtSigned(e.pnl) : ''}
                              </span>
                              {tab === 'pendentes' && (
                                <button
                                  onClick={ev => { ev.stopPropagation(); handleUnfollow(e.pick_id, e.pick_type) }}
                                  className="flex items-center justify-center w-8 h-8 rounded-lg text-ink-4 hover:text-red-400 hover:bg-red-400/10 transition-colors shrink-0"
                                  title="Remover pick"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              )}
                            </div>
                          </button>
                        )
                      })}
                    </div>
                  </div>
                )}

                {/* Paginação · só no modo Todos (daysBack=0) */}
                {daysBack === 'tudo' && filteredTabEntries.length > PAGE_SIZE && (
                  <div className="flex items-center justify-center gap-2 flex-wrap">
                    <button
                      disabled={todayPage === 0}
                      onClick={() => setTodayPage(p => p - 1)}
                      className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-line-strong text-ink-2 hover:border-ink-4 disabled:opacity-30 transition-colors"
                    >Ant</button>
                    <span className="text-xs text-ink-3">
                      {todayPage * PAGE_SIZE + 1}–{Math.min((todayPage + 1) * PAGE_SIZE, filteredTabEntries.length)} de {filteredTabEntries.length}
                    </span>
                    <button
                      disabled={(todayPage + 1) * PAGE_SIZE >= filteredTabEntries.length}
                      onClick={() => setTodayPage(p => p + 1)}
                      className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-line-strong text-ink-2 hover:border-ink-4 disabled:opacity-30 transition-colors"
                    >Próx</button>
                  </div>
                )}

                {/* Carregar mais resolvidos do servidor · histórico cresce sem limite */}
                {tab === 'resolvidos' && daysBack === 'tudo' && data?.has_more_resolved && (
                  <button
                    onClick={loadMoreResolved}
                    disabled={loadingMore}
                    className="w-full text-center text-xs text-ink-3 hover:text-ink-2 disabled:opacity-50 transition-colors py-2 border border-line rounded-md hover:border-line-strong font-semibold"
                  >
                    {loadingMore ? 'Carregando...' : 'Carregar apostas mais antigas'}
                  </button>
                )}
              </>
            )}
            </motion.div>
            </AnimatePresence>

          </div>
        )}

      <AnimatePresence>
      {showRemoved && (
        <motion.div
          variants={toastUp} initial="hidden" animate="visible" exit="exit"
          className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 bg-red-600 text-ink-1 text-sm font-semibold px-5 py-3 rounded-md shadow-lg whitespace-nowrap"
        >
          Pick removido da sua banca
        </motion.div>
      )}
      </AnimatePresence>
    </PageShell>
  )
}
