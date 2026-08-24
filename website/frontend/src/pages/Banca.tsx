import { useEffect, useState, useCallback } from 'react'
import { TrendingUp, Info } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { backdropFade, dialogScale } from '../lib/motion'
import api from '../services/api'
import { useAuth } from '../context/AuthContext'
import { useOnboarding } from '../context/OnboardingContext'
import { EVENTO_CONFIGURAR_BANCA } from '../components/onboarding/constantes'
import PageShell from '../components/PageShell'
import ProfitChart from '../components/ProfitChart'
import SuggestionDetail from '../components/SuggestionDetail'
import { fmtBRL, fmtSigned, fmtUnits } from '../utils/format'
import { getResultStyle, PICK_TYPE_CLS } from '../utils/resultStyle'
import { TeamLogo } from '../components/TeamLogo'
import { Button, NumberTicker, PillGroup, Spinner } from '../components/ui'
import { PERIODOS, PERIODO_PADRAO, janelaDoPeriodo, type PeriodoKey } from '../lib/periodo'
import MonthlyCloseSection from '../components/MonthlyCloseSection'

const SOURCE_LBL: Record<string, string> = {
  vip: 'VIP', free: 'Free', multipla: 'Múlt.', alavancagem: 'Alav.',
}

// lock overlay para free
// modal de setup
function SetupModal({ current, locked, onSave, onClose, onWithdraw }: {
  current: { start: number; unitValue: number }
  locked?: boolean
  onSave: (start: number, unitValue: number) => void
  onClose: () => void
  onWithdraw: () => void
}) {
  const [start,     setStart]     = useState(String(current.start))
  const [unitValue, setUnitValue] = useState(String(current.unitValue))
  const [err,       setErr]       = useState('')
  const [loading,   setLoading]   = useState(false)

  const startNum  = parseFloat(start.replace(',', '.')) || 0
  const uvNum     = parseFloat(unitValue.replace(',', '.')) || 0
  const suggested = startNum > 0 ? (startNum / 100).toFixed(2) : ''

  // Validação de risco de banca em tempo real
  const totalUnits   = startNum > 0 && uvNum > 0 ? startNum / uvNum : null
  const unitPct      = startNum > 0 && uvNum > 0 ? (uvNum / startNum) * 100 : null
  const isBlocked    = totalUnits !== null && totalUnits < 20
  const isWarning    = totalUnits !== null && totalUnits >= 20 && totalUnits < 50
  const maxUnitSafe  = startNum > 0 ? (startNum / 20).toFixed(2) : null

  const bancaStatus = isBlocked ? 'blocked'
    : isWarning ? 'warning'
    : totalUnits !== null ? 'ok'
    : null

  const handleSave = async () => {
    setErr('')
    const s  = parseFloat(start.replace(',', '.'))
    const uv = parseFloat(unitValue.replace(',', '.'))
    if (!s || s <= 0)          { setErr('Banca inicial deve ser maior que zero.'); return }
    if (!uv || uv <= 0)        { setErr('Valor da unidade deve ser maior que zero.'); return }
    if (isBlocked)             { setErr(`Unidade muito alta. Máximo permitido: ${fmtBRL(parseFloat(maxUnitSafe ?? '0'))} para ter 20 unidades mínimas.`); return }
    setLoading(true)
    try {
      await api.post('/banca/setup', { bankroll_start: s, unit_value: uv })
      onSave(s, uv)
    } catch (e: any) {
      setErr(e.response?.data?.detail ?? 'Erro ao salvar.')
    } finally {
      setLoading(false)
    }
  }

  if (locked) {
    return (
      <motion.div
        variants={backdropFade} initial="hidden" animate="visible" exit="exit"
        className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center px-4" onClick={onClose}
      >
        <motion.div variants={dialogScale} className="bg-surface-1 border border-line-strong rounded-lg p-6 max-w-sm w-full overflow-y-auto max-h-[92dvh]"
          onClick={e => e.stopPropagation()}>
          <h2 className="text-ink-1 font-bold text-lg mb-2">Já configurada este mês</h2>
          <p className="text-ink-2 text-sm leading-relaxed mb-4">
            Pra manter o histórico de risco confiável, a banca só pode ser configurada uma vez por
            mês. Se você quer tirar um valor agora, use o botão "Sacar" (fica registrado no
            histórico). Pra reconfigurar do zero, espera o fechamento mensal automático.
          </p>
          <div className="flex flex-col gap-2">
            <button onClick={() => { onClose(); onWithdraw() }} className="btn-primary w-full py-2.5 text-sm">
              Sacar da banca
            </button>
            <button onClick={onClose} className="btn-ghost w-full py-2.5 text-sm">Entendi</button>
          </div>
        </motion.div>
      </motion.div>
    )
  }

  return (
    <motion.div
      variants={backdropFade} initial="hidden" animate="visible" exit="exit"
      className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center px-4"
    >
      <motion.div variants={dialogScale} className="bg-surface-1 border border-line rounded-lg p-6 w-full max-w-sm overflow-y-auto max-h-[92dvh]">
        <h2 className="text-ink-1 font-bold text-lg mb-1">Configurar banca</h2>
        <p className="text-ink-3 text-xs mb-5">Define banca, unidade e meta como um tipster profissional.</p>

        <div className="space-y-4">
          <div>
            <label className="text-xs text-ink-3 block mb-1.5">Banca inicial (R$)</label>
            <input type="number" min="1" step="0.01" value={start}
              onChange={e => setStart(e.target.value)} className="input w-full" placeholder="Ex: 500" />
          </div>

          <div>
            <label className="text-xs text-ink-3 block mb-1.5">
              Valor de 1 unidade (R$)
              <span className="text-ink-4 ml-1">quanto você aposta por unidade</span>
            </label>
            <input
              type="number" min="0.01" step="0.01" value={unitValue}
              onChange={e => setUnitValue(e.target.value)}
              className={`input w-full ${isBlocked ? 'border-red-500/60 focus:border-red-500' : isWarning ? 'border-yellow-500/60 focus:border-yellow-500' : ''}`}
              placeholder="Ex: 5"
            />
            {startNum > 0 && (
              <p className="text-ink-4 text-xs mt-1">
                Sugerido: <button type="button" onClick={() => setUnitValue(suggested)}
                  className="text-accent-ink underline hover:text-green-400">
                  {fmtBRL(parseFloat(suggested) || 0)}
                </button>
                {' '}(1% da banca, gestão conservadora)
              </p>
            )}

            {/* Indicador de saúde da banca */}
            {bancaStatus === 'blocked' && totalUnits !== null && (
              <div className="mt-2 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2 text-xs">
                <p className="text-red-400 font-black mb-0.5">Bloqueado: risco de ruína</p>
                <p className="text-red-300">
                  Com R${fmtBRL(uvNum)} por unidade sua banca teria apenas <strong>{Math.floor(totalUnits)} unidades</strong>.
                  Menos de 20 unidades é alto risco de ruína total.
                </p>
                <p className="text-red-400 mt-1 font-semibold">
                  Máximo permitido: <button type="button" onClick={() => setUnitValue(maxUnitSafe ?? '')}
                    className="underline hover:text-red-300">{fmtBRL(parseFloat(maxUnitSafe ?? '0'))}</button> por unidade
                </p>
              </div>
            )}
            {bancaStatus === 'warning' && totalUnits !== null && unitPct !== null && (
              <div className="mt-2 bg-yellow-500/10 border border-yellow-500/30 rounded-lg px-3 py-2 text-xs">
                <p className="text-yellow-400 font-black mb-0.5">Atenção: unidade acima do ideal</p>
                <p className="text-yellow-300">
                  Sua banca teria <strong>{Math.floor(totalUnits)} unidades</strong> ({unitPct.toFixed(1)}% por unidade).
                  Recomendado: mínimo 50 unidades (≤ 2% por unidade).
                </p>
                <p className="text-yellow-400 mt-1 font-semibold">
                  Ideal: <button type="button" onClick={() => setUnitValue(suggested)}
                    className="underline hover:text-yellow-300">{fmtBRL(parseFloat(suggested) || 0)}</button> por unidade
                </p>
              </div>
            )}
            {bancaStatus === 'ok' && totalUnits !== null && (
              <div className="mt-2 flex items-center gap-1.5 text-xs text-accent-ink">
                <span className="font-bold">Banca saudável</span>
                <span className="text-ink-4">·</span>
                <span className="text-ink-2">{Math.floor(totalUnits)} unidades totais</span>
              </div>
            )}
          </div>

        </div>

        <div className="mt-4 bg-surface-2/50 rounded-lg px-3 py-2 text-xs text-ink-2">
          <p className="font-semibold text-ink-2 mb-0.5">Como funciona:</p>
          <p>Pick recomenda 2u: você aposta 2 × R$ {unitValue || '?'} = <strong className="text-ink-1">{fmtBRL((parseFloat(unitValue) || 0) * 2)}</strong></p>
          <p className="text-ink-3 mt-0.5">Yield = lucro em unidades / unidades apostadas × 100%</p>
        </div>

        {err && <p className="text-red-400 text-xs mt-3">{err}</p>}

        <div className="flex gap-3 mt-5">
          <button onClick={handleSave} disabled={loading || isBlocked}
            className="btn-primary flex-1 py-2.5 disabled:opacity-40 disabled:cursor-not-allowed">
            {loading ? 'Salvando...' : 'Salvar'}
          </button>
          <button onClick={onClose} className="btn-ghost flex-1 py-2.5 text-sm">Cancelar</button>
        </div>
      </motion.div>
    </motion.div>
  )
}

export default function Banca() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const { retomar: retomarTour } = useOnboarding()

  const [data,    setData]    = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(false)
  const [period,  setPeriod]  = useState<PeriodoKey>(PERIODO_PADRAO)
  const [showSetup, setShowSetup]           = useState(false)
  const [detailPick, setDetailPick] = useState<{ id: number; pick_type: string } | null>(null)


  const load = useCallback((p: PeriodoKey) => {
    setLoading(true)
    setError(false)
    // Sempre from/to, nunca `days`: a janela sai de lib/periodo, que e' a mesma
    // conta que Meus Picks usa. Com `days` solto cada tela fazia o proprio
    // calculo de fuso e as duas divergiam na virada da meia-noite.
    const j = janelaDoPeriodo(p)
    const params: Record<string, string> = j ? { from_date: j.de, to_date: j.ate } : {}
    api.get('/banca', { params })
      .then(r => setData(r.data))
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load(period)
  }, [period, load])


  const handleSave = (start: number, unitValue: number) => {
    setShowSetup(false)
    setData((d: any) => d ? { ...d, bankroll_start: start, unit_value: unitValue } : d)
    load(period)
    // Configurou pelo tour: o tour volta já no passo seguinte, porque o passo
    // da banca acabou de ser cumprido de verdade. Fora do tour não faz nada.
    retomarTour(true)
  }

  /*
   * O tour pedindo o formulário DE VERDADE.
   *
   * O passo da banca tem um botão "Configurar minha banca agora" que abre este
   * mesmo SetupModal, em vez de mandar a pessoa anotar mentalmente para fazer
   * depois. Chega por evento de janela porque quem dispara vive num portal no
   * body e não enxerga o estado desta página.
   *
   * O `retomarTour()` da limpeza cobre o caminho de fuga: se a pessoa sair de
   * /banca com o tour pausado (voltar do navegador, clicar em outro link), o
   * tour volta a desenhar em vez de ficar invisível para sempre.
   */
  useEffect(() => {
    const abrir = () => setShowSetup(true)
    window.addEventListener(EVENTO_CONFIGURAR_BANCA, abrir)
    return () => {
      window.removeEventListener(EVENTO_CONFIGURAR_BANCA, abrir)
      retomarTour()
    }
  }, [retomarTour])

  const pnlColor = (v: number | null) =>
    v == null ? 'text-ink-4' : v > 0 ? 'text-accent-ink' : v < 0 ? 'text-red-400' : 'text-ink-2'

  const temGrafico = (data?.chart?.length ?? 0) >= 2
  const chartData = (data?.chart ?? []).map((p: any, i: number, arr: any[]) => ({
    match_date: p.date,
    profit: i === 0
      ? p.bankroll - (data?.bankroll_start ?? 100)
      : p.bankroll - arr[i - 1].bankroll,
  }))

  // meta progress
  const current = data?.bankroll_current ?? data?.bankroll_start ?? 0
  const start   = data?.bankroll_start ?? 100

  // ganho em unidades (exclui alavancagem, igual ao total_pnl)
  const ganhoUnidades = (data?.unit_value ?? 0) > 0 ? (data?.total_pnl ?? 0) / data.unit_value : 0

  // distribuição
  const distTotal = (data?.greens ?? 0) + (data?.reds ?? 0) + (data?.push ?? 0) + (data?.half_wins ?? 0) + (data?.half_loss ?? 0)
  const distItems = [
    { label: 'GREEN',   value: data?.greens    ?? 0, color: 'bg-green-500',  text: 'text-green-400'  },
    { label: 'RED',     value: data?.reds      ?? 0, color: 'bg-red-500',    text: 'text-red-400'    },
    { label: '½ WIN',   value: data?.half_wins ?? 0, color: 'bg-teal-500',   text: 'text-teal-400'   },
    { label: '½ LOSS',  value: data?.half_loss ?? 0, color: 'bg-orange-500', text: 'text-orange-400' },
    { label: 'PUSH',    value: data?.push      ?? 0, color: 'bg-ink-4',   text: 'text-ink-2'   },
  ]

  return (
    <PageShell
      title="Minha Banca"
      description="Acompanhe o crescimento da sua banca a partir dos picks que você apostou."
      noindex
      width="full"
      bar={{
        back: true,
        title: 'Minha Banca',
        sub: (
          <span className="flex items-center gap-2">
            Acompanhe o crescimento dos picks que você apostou
            {data?.unit_value && (
              <span className="text-ink-2 font-semibold">
                1 unidade = <span className="font-mono text-ink-1">{fmtBRL(Number(data.unit_value))}</span>
              </span>
            )}
          </span>
        ),
        actions: (
          <>
            <Button variant="ghost" size="sm" onClick={() => navigate('/banca/saque')}>
              Sacar
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowSetup(true)}
              className={data?.can_configure === false ? 'opacity-50' : undefined}
              title={data?.can_configure === false ? 'Já configurada este mês' : undefined}
              data-tour="banca-configurar"
            >
              Configurar
            </Button>
          </>
        ),
      }}
    >
      <AnimatePresence>
      {showSetup && (
        <SetupModal
          current={{ start: data?.bankroll_start ?? 100, unitValue: data?.unit_value ?? 1 }}
          locked={data?.can_configure === false}
          onSave={handleSave}
          onClose={() => { setShowSetup(false); retomarTour() }}
          onWithdraw={() => navigate('/banca/saque')}
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
            <p className="text-ink-2 font-semibold mb-1">Erro ao carregar sua banca</p>
            <p className="text-ink-4 text-sm mb-4">Não foi possível conectar ao servidor. Verifique sua conexão.</p>
            <button onClick={() => load(period)} className="text-sm text-green-400 hover:text-green-300 font-semibold transition-colors">
              Tentar novamente
            </button>
          </div>
        ) : (
          <div className="space-y-6">

            {/* Período sempre à vista.
                Era um painel dobrável com um grupo só dentro · dois cliques
                (abrir, escolher) e mais um pra fechar, pro filtro PRINCIPAL da
                tela. Meus Picks já mostrava a mesma escolha em fila aberta;
                agora as duas usam a mesma fila e o mesmo vocabulário
                (lib/periodo). Painel dobrável continua fazendo sentido onde há
                vários grupos, como em Resultados e Estatísticas. */}
            <PillGroup
              options={PERIODOS.map(p => ({ value: p.key, label: p.label }))}
              value={period}
              onChange={setPeriod}
              className="mb-5"
            />

            {/* Stats principais.
                `data-tour` é a âncora do passo "Acompanhe sua evolução" do
                onboarding · ver components/onboarding/steps.tsx. */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4" data-tour="banca-resumo">
              {[
                {
                  label: 'Banca atual',
                  value: data?.total_pnl ?? 0,
                  formatter: (v: number) => fmtSigned(v),
                  color: (data?.total_pnl ?? 0) >= 0 ? 'text-accent-ink' : 'text-red-400',
                  sub: `${fmtBRL(current)} banca total`,
                },
                {
                  label: 'Yield (tipster)',
                  value: data?.yield_roi ?? 0,
                  formatter: (v: number) => `${v >= 0 ? '+' : ''}${Math.round(v)}%`,
                  color: (data?.yield_roi ?? 0) >= 0 ? 'text-blue-400' : 'text-red-400',
                  sub: data?.ia_roi != null
                    ? `ROI da IA: ${data.ia_roi >= 0 ? '+' : ''}${data.ia_roi}%`
                    : `ROI banca: ${(data?.roi ?? 0) >= 0 ? '+' : ''}${data?.roi ?? 0}%`,
                },
                {
                  label: 'Win rate',
                  value: data?.win_rate ?? 0,
                  formatter: (v: number) => `${Math.round(v)}%`,
                  color: (data?.win_rate ?? 0) >= 55 ? 'text-accent-ink' : 'text-ink-2',
                  sub: `${data?.greens ?? 0}G / ${data?.reds ?? 0}R de ${data?.total_resolved ?? 0}`,
                },
                {
                  label: 'Ganho por unidade',
                  value: ganhoUnidades,
                  // fmtUnits e não toFixed: o resto da tela escreve 1.229,22
                  // e este tile respondia 122.9u, com ponto decimal de inglês.
                  formatter: (v: number) => fmtUnits(v),
                  color: ganhoUnidades >= 0 ? 'text-accent-ink' : 'text-red-400',
                  sub: 'excl. alavancagem',
                },
              ].map(({ label, value, formatter, color, sub }) => (
                <div key={label} className="stat-card text-center">
                  {/* No celular cada tile tem ~150px: em text-3xl um "+R$ 1.229,22" quebrava
                      entre o "R$" e o número, como se fossem duas informações. */}
                  <NumberTicker value={value} formatter={formatter} className={`font-mono text-2xl sm:text-3xl font-black whitespace-nowrap ${color}`} />
                  <div className="text-xs text-ink-3 mt-1">{label}</div>
                  <div className="text-[10px] text-ink-4 mt-0.5">{sub}</div>
                </div>
              ))}
            </div>

            {/* Alavancagem · o que entra nesta banca é caminho ENCERRADO, não
                green de degrau.

                Virou CARD COM BOTÃO em 2026-08-20 (pedido do usuário). Antes
                era só uma frase de aviso, e depois uma frase sublinhada: as
                duas versões diziam o que a alavancagem NÃO é sem dar onde
                vê-la, e link dentro de texto corrido não lê como destino. O
                aviso continua, agora com a porta ao lado dele. */}
            <div className="card p-4 flex items-center gap-3 -mt-2">
              <Info className="w-4 h-4 text-ink-4 shrink-0 hidden sm:block" />
              <p className="text-[11px] text-ink-3 leading-relaxed flex-1">
                Alavancagem entra nesta banca só quando você encerra o caminho.
                O que está rodando fica de fora.
              </p>
              <button
                onClick={() => navigate('/banca/alavancagem')}
                className="flex items-center gap-1.5 text-xs font-semibold text-ink-2 hover:text-ink-1 border border-line-strong hover:border-orange-400/40 px-3 py-2 rounded-md transition-colors shrink-0 min-h-[36px]"
              >
                <TrendingUp className="w-3.5 h-3.5 shrink-0 text-orange-400" />
                Ver alavancagem
              </button>
            </div>

            {/*
              Painel: gráfico à esquerda, sequência e distribuição à direita.
              Empilhados, os três ocupavam três telas de rolagem numa página que
              agora tem largura de sobra · e o gráfico, sozinho na faixa toda,
              era o que mais crescia. Lado a lado, a leitura fecha num golpe:
              a curva, o momento e o saldo por tipo de resultado.
              Abaixo de xl volta a empilhar, que é o certo no celular.
            */}
            <div className={`grid grid-cols-1 gap-4 items-stretch ${
              temGrafico ? 'xl:grid-cols-3' : 'sm:grid-cols-2'
            }`}>

              {/* Gráfico de evolução */}
              {temGrafico && (
                <div className="card p-5 xl:col-span-2" data-tour="banca-evolucao">
                  <div className="flex items-center justify-between mb-4">
                    <p className="text-xs text-ink-3 font-semibold">Evolução da banca</p>
                    <span className={`text-sm font-black ${(data?.total_pnl ?? 0) >= 0 ? 'text-accent-ink' : 'text-red-400'}`}>
                      {fmtSigned(data?.total_pnl ?? 0)}
                    </span>
                  </div>
                  <ProfitChart data={chartData} unit="R$" height={240} />
                </div>
              )}

              {/* Com gráfico, os dois painéis empilham numa coluna ao lado
                  dele. Sem gráfico (mês zerado, conta nova), eles se espalham
                  lado a lado na largura toda · presos em 1/3 sobrava dois
                  terços de preto, que foi o que apareceu logo depois do
                  primeiro "zerar o mês". `contents` desfaz este invólucro e
                  entrega os dois filhos direto pra grade de fora. */}
              <div className={temGrafico ? 'flex flex-col gap-4' : 'contents'}>

              {/* Streak pessoal */}
              <div className="card p-5">
                <p className="text-xs text-ink-3 font-semibold mb-4">Sequência pessoal</p>
                <div className="flex items-center justify-around">
                  <div className="text-center">
                    <div className={`text-4xl font-black ${data?.streak_type === 'green' ? 'text-accent-ink' : data?.streak_type === 'red' ? 'text-red-400' : 'text-ink-4'}`}>
                      {data?.streak > 0 ? data.streak : 0}
                    </div>
                    <div className="text-xs text-ink-3 mt-1">
                      {data?.streak_type === 'green' ? 'Greens seguidos' : data?.streak_type === 'red' ? 'Reds seguidos' : 'Sequência atual'}
                    </div>
                  </div>
                  <div className="w-px h-12 bg-surface-2" />
                  <div className="text-center">
                    <div className="text-4xl font-black text-yellow-400">
                      {data?.best_streak > 0 ? data.best_streak : 0}
                    </div>
                    <div className="text-xs text-ink-3 mt-1">Melhor sequência</div>
                  </div>
                </div>
              </div>

              {/* Distribuição de resultados */}
              <div className="card p-5">
                <p className="text-xs text-ink-3 font-semibold mb-4">Distribuição de resultados</p>
                {distTotal === 0 ? (
                  <p className="text-ink-4 text-xs text-center py-4">Sem picks resolvidos ainda.</p>
                ) : (
                  <div className="space-y-2">
                    {distItems.map(({ label, value, color, text }) => (
                      <div key={label} className="flex items-center gap-2">
                        <span className={`text-[10px] font-black w-12 text-right shrink-0 ${text}`}>{label}</span>
                        <div className="flex-1 bg-surface-2 rounded-full h-2 overflow-hidden">
                          <div
                            className={`h-2 rounded-full ${color}`}
                            style={{ width: `${distTotal > 0 ? Math.round(value / distTotal * 100) : 0}%` }}
                          />
                        </div>
                        <span className="text-xs text-ink-3 w-8 text-right shrink-0">{value}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              </div>
            </div>

            {/* Melhor e pior pick */}
            {(data?.best_pick || data?.worst_pick) && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {data?.best_pick && (
                  <div className="card p-4 border-green-500/20 bg-green-500/5">
                    <p className="text-xs text-accent-ink font-black mb-2">Melhor pick apostado</p>
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="flex items-center gap-1.5 mb-0.5">
                          <TeamLogo id={data.best_pick.home_team_id} name={data.best_pick.home_team_name ?? ''} size={16} />
                          <p className="text-sm text-ink-1 font-semibold">{data.best_pick.home_team_name ?? `Pick #${data.best_pick.pick_id}`}</p>
                        </div>
                        <p className="text-xs text-ink-3">{data.best_pick.market ?? ''}</p>
                        <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border mt-1 inline-block ${PICK_TYPE_CLS[data.best_pick.pick_type] ?? ''}`}>
                          {SOURCE_LBL[data.best_pick.pick_type] ?? data.best_pick.pick_type}
                        </span>
                      </div>
                      <span className="font-mono text-2xl font-black text-accent-ink">
                        +{fmtBRL(data.best_pick.pnl)}
                      </span>
                    </div>
                  </div>
                )}
                {data?.worst_pick && data.worst_pick.pnl < 0 && (
                  <div className="card p-4 border-red-500/20 bg-red-500/5">
                    <p className="text-xs text-red-400 font-black mb-2">Pior pick apostado</p>
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="flex items-center gap-1.5 mb-0.5">
                          <TeamLogo id={data.worst_pick.home_team_id} name={data.worst_pick.home_team_name ?? ''} size={16} />
                          <p className="text-sm text-ink-1 font-semibold">{data.worst_pick.home_team_name ?? `Pick #${data.worst_pick.pick_id}`}</p>
                        </div>
                        <p className="text-xs text-ink-3">{data.worst_pick.market ?? ''}</p>
                        <span className={`text-[10px] font-black px-1.5 py-0.5 rounded border mt-1 inline-block ${PICK_TYPE_CLS[data.worst_pick.pick_type] ?? ''}`}>
                          {SOURCE_LBL[data.worst_pick.pick_type] ?? data.worst_pick.pick_type}
                        </span>
                      </div>
                      <span className="font-mono text-2xl font-black text-red-400">
                        −{fmtBRL(Math.abs(data.worst_pick.pnl))}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Comparação com IA */}
            {data?.ia_roi != null && (
              <div className="card p-5">
                <p className="text-xs text-ink-3 font-semibold mb-4">Você vs IA</p>
                <div className="font-mono grid grid-cols-3 gap-2 sm:gap-4">
                  <div className="text-center">
                    <div className={`text-xl sm:text-2xl font-black ${(data?.yield_roi ?? 0) >= 0 ? 'text-blue-400' : 'text-red-400'}`}>
                      {(data?.yield_roi ?? 0) >= 0 ? '+' : ''}{data.yield_roi ?? 0}%
                    </div>
                    <div className="text-xs text-ink-3 mt-1 font-semibold">Seu Yield</div>
                    <div className="text-[10px] text-ink-4 mt-0.5">lucro / unidades</div>
                  </div>
                  <div className="text-center">
                    <div className={`text-xl sm:text-2xl font-black ${(data?.roi ?? 0) >= 0 ? 'text-blue-400' : 'text-red-400'}`}>
                      {(data?.roi ?? 0) >= 0 ? '+' : ''}{data.roi ?? 0}%
                    </div>
                    <div className="text-xs text-ink-3 mt-1 font-semibold">ROI banca</div>
                    <div className="text-[10px] text-ink-4 mt-0.5">{data.total_resolved} picks</div>
                  </div>
                  <div className="text-center">
                    <div className={`text-xl sm:text-2xl font-black ${data.ia_roi >= 0 ? 'text-accent-ink' : 'text-red-400'}`}>
                      {data.ia_roi >= 0 ? '+' : ''}{data.ia_roi}%
                    </div>
                    <div className="text-xs text-ink-3 mt-1 font-semibold">Yield da IA</div>
                    <div className="text-[10px] text-ink-4 mt-0.5">todos os picks VIP</div>
                  </div>
                </div>
                {data.yield_roi != null && data.ia_roi != null && (
                  <div className={`mt-4 text-center text-xs font-semibold ${data.yield_roi >= data.ia_roi ? 'text-green-400' : 'text-ink-3'}`}>
                    {data.yield_roi >= data.ia_roi
                      ? <span className="flex items-center justify-center gap-1"><TrendingUp className="w-3.5 h-3.5" /> Você está superando a IA neste período!</span>
                      : `Diferença de ${(data.ia_roi - data.yield_roi).toFixed(1)}% em relação à IA`}
                  </div>
                )}
              </div>
            )}

            {/* Lista de picks agrupada por data */}
            {(() => {
              const allEntries: any[] = [...(data?.entries ?? [])].reverse().slice(0, 10)
              const todayKey     = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })
              const yesterdayKey = new Date(Date.now() - 86400000).toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })
              const dayLabel = (key: string) =>
                key === todayKey     ? 'Hoje'
                : key === yesterdayKey ? 'Ontem'
                : new Date(key + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' })

              const grouped = allEntries.reduce((acc: Record<string, any[]>, e: any) => {
                const key = e.followed_at
                  ? new Date(e.followed_at).toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })
                  : 'sem-data'
                if (!acc[key]) acc[key] = []
                acc[key].push(e)
                return acc
              }, {})
              const sortedKeys = Object.keys(grouped).sort((a, b) => b.localeCompare(a))

              const PickRow = ({ e }: { e: any }) => {
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
                            : e.pick_type === 'multipla' ? 'Múltipla'
                            : e.pick_type === 'alavancagem' ? 'Alavancagem'
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
                      <p className="text-xs text-ink-4 truncate">
                        {e.market ?? ''}
                        {e.line ? ` · ${e.line}` : ''}
                        {e.actual_odd
                          ? <> · <span className="text-ink-2">Odd {Number(e.actual_odd).toFixed(2)}</span>{Math.abs(Number(e.actual_odd) - Number(e.odd)) > 0.001 ? <span className="text-ink-4"> (pick: {Number(e.odd).toFixed(2)})</span> : null}</>
                          : e.odd ? ` · Odd ${Number(e.odd).toFixed(2)}` : ''}
                      </p>
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
                    </div>
                  </button>
                )
              }

              return (
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <p className="text-xs text-ink-3 font-semibold">
                      Últimos picks apostados
                    </p>
                    <Link to="/meus-picks" className="text-xs text-accent-ink hover:text-green-400 transition-colors font-semibold">
                      Ver todos
                    </Link>
                  </div>

                  {!allEntries.length ? (
                    <div className="card p-12 text-center border-dashed">
                      <p className="text-ink-3 text-sm font-semibold mb-2">Nenhum pick apostado ainda</p>
                      <p className="text-ink-4 text-xs mb-4">
                        Clique em "Apostar" nos picks da página Picks para registrar suas apostas aqui.
                      </p>
                      <button onClick={() => navigate('/picks')} className="btn-primary text-sm px-6 py-2.5">
                        Ver picks
                      </button>
                    </div>
                  ) : (
                    <div className="card overflow-hidden">
                      {sortedKeys.map(dateKey => (
                        <div key={dateKey}>
                          <div className="flex items-center gap-2 px-4 py-2 bg-surface-1/60 border-b border-line/60">
                            <span className="text-[10px] font-black text-ink-3 capitalize">
                              {dayLabel(dateKey)}
                            </span>
                            <span className="text-[10px] text-ink-4">{grouped[dateKey].length} pick{grouped[dateKey].length !== 1 ? 's' : ''}</span>
                          </div>
                          <div className="divide-y divide-line/60">
                            {grouped[dateKey].map((e: any) => <PickRow key={e.id} e={e} />)}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })()}

            <MonthlyCloseSection />

          </div>
        )}
    </PageShell>
  )
}
