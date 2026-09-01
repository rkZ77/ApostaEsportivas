import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { TrendingUp, TrendingDown, X, BadgeCheck, Share2, Check, ChevronRight, ArrowLeft } from 'lucide-react'
import api from '../services/api'
import { fmtBRL, fmtUnits } from '../utils/format'
import { backdropFade, sheetUp, tabFade } from '../lib/motion'
import { useNotifications } from '../context/NotificationContext'
import { useAuth } from '../context/AuthContext'

// Quem decide se este modal aparece é a notificação `monthly_close` do
// servidor, não mais um localStorage por navegador. O modelo antigo perdia o
// fechamento pra sempre quando o usuário fechava o popup (ou quando a chamada
// falhava), e reabria de novo em cada aparelho diferente.

interface AlavancagemMonthData {
  configured: boolean
  current_bankroll: number
  initial_bankroll: number
  closed_this_month: number
  busted_this_month: boolean
  realized_this_month: number
}

interface CloseData {
  month_label: string
  month_key: string
  total_pnl: number
  greens: number
  reds: number
  push: number
  half_wins: number
  half_loss: number
  total_resolved: number
  total_followed: number
  bankroll_start: number
  bankroll_current: number
  unit_value: number
  paid_plan: boolean
  alavancagem: AlavancagemMonthData | null
  already_closed: boolean
}

const MOCK_DATA: CloseData = {
  month_label: 'Junho 2026',
  month_key: '2026-06',
  total_pnl: 187.50,
  greens: 14,
  reds: 6,
  push: 1,
  half_wins: 2,
  half_loss: 1,
  total_resolved: 24,
  total_followed: 26,
  bankroll_start: 500,
  bankroll_current: 687.50,
  unit_value: 5,
  paid_plan: true,
  alavancagem: {
    configured: true,
    current_bankroll: 320,
    initial_bankroll: 100,
    closed_this_month: 2,
    busted_this_month: true,
    realized_this_month: 240,
  },
  already_closed: false,
}

type Step = 'summary' | 'edit' | 'success'

interface Props {
  onClose: () => void
}

export default function MonthlyCloseModal({ onClose }: Props) {
  const { isAdmin } = useAuth()
  // Dados fabricados só pra admin · ver GlobalModals em App.tsx. Blindado aqui
  // também porque o modal abre pelo sino e pela Banca, não só pelo popup.
  const isPreview = isAdmin && new URLSearchParams(window.location.search).get('preview') === 'monthly'
  const { pendingMonthlyClose, markRead, refresh } = useNotifications()

  const [data, setData]       = useState<CloseData | null>(isPreview ? MOCK_DATA : null)
  const [loading, setLoading] = useState(!isPreview)
  const [failed, setFailed]   = useState(false)
  const [step, setStep]       = useState<Step>('summary')
  const [newBanca, setNewBanca] = useState('')
  const [saving, setSaving]   = useState(false)
  const [savedValue, setSavedValue] = useState(0)
  const [copied, setCopied]   = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (isPreview) return
    api.get('/banca/monthly-close')
      .then(r => setData(r.data))
      // Erro de rede/servidor não pode mais "queimar" o mês: nada é marcado
      // como visto, então o fechamento continua no sino pra tentar de novo.
      .catch(() => setFailed(true))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (step === 'edit') setTimeout(() => inputRef.current?.focus(), 100)
  }, [step])

  // Fecha automaticamente após mostrar o sucesso
  useEffect(() => {
    if (step !== 'success') return
    const t = setTimeout(() => handleClose(), 2000)
    return () => clearTimeout(t)
  }, [step])

  // Fechar marca a notificação como lida (não reabre sozinho), mas ela continua
  // no sino: enquanto a banca não for confirmada, o fechamento segue acessível.
  const handleClose = () => {
    if (pendingMonthlyClose) markRead(pendingMonthlyClose.id)
    onClose()
  }

  const parseBanca = () => {
    const raw = newBanca.replace(/\./g, '').replace(',', '.')
    return parseFloat(raw)
  }

  // Botão 1: salva direto com o valor do fechamento
  const handleUpdateDirect = async () => {
    if (!data) return
    setSaving(true)
    try {
      await api.post('/banca/setup', {
        bankroll_start: data.bankroll_current,
        unit_value: data.unit_value,
        monthly_close_month_key: data.month_key,
      })
      setSavedValue(data.bankroll_current)
      setStep('success')
      refresh()
    } catch { }
    finally { setSaving(false) }
  }

  // Botão 2 (edição personalizada)
  const handleSave = async () => {
    if (!data) return
    const value = parseBanca()
    if (isNaN(value) || value <= 0) return
    setSaving(true)
    try {
      await api.post('/banca/setup', {
        bankroll_start: value,
        unit_value: data.unit_value,
        monthly_close_month_key: data.month_key,
      })
      setSavedValue(value)
      setStep('success')
      refresh()
    } catch { }
    finally { setSaving(false) }
  }

  const handleShare = async (d: CloseData) => {
    const ganhoU = d.unit_value > 0 ? d.total_pnl / d.unit_value : 0
    const isProfit = d.total_pnl >= 0
    const text = [
      `Fechamento de ${d.month_label} na Pick IA`,
      `${isProfit ? '+' : '-'}${fmtBRL(Math.abs(d.total_pnl))} (${fmtUnits(ganhoU)})`,
      `${d.greens}G / ${d.reds}R em ${d.total_resolved} picks`,
      `Banca: ${fmtBRL(d.bankroll_current - d.total_pnl)} -> ${fmtBRL(d.bankroll_current)}`,
      '',
      'pickia.com.br',
    ].join('\n')
    if (navigator.share) {
      try { await navigator.share({ text }) } catch { /* cancelou */ }
    } else {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2500)
    }
  }

  if (loading) return null

  const hasAlavActivity = !!data?.alavancagem && (data.alavancagem.closed_this_month > 0 || data.alavancagem.busted_this_month)

  // Estado vazio explícito em vez de fechar sozinho: o modal também é aberto
  // de propósito (sino e página Banca), e um popup que abre e some sem dizer
  // nada parece bug.
  if (failed || !data || (data.total_followed === 0 && !hasAlavActivity)) {
    return (
      <motion.div
        variants={backdropFade} initial="hidden" animate="visible" exit="exit"
        className="fixed inset-0 bg-black/90 backdrop-blur-sm z-[9998] flex items-end sm:items-center justify-center"
      >
        <motion.div variants={sheetUp} className="bg-surface-0 border border-line rounded-t-2xl sm:rounded-lg w-full sm:max-w-sm shadow-2xl">
          <div className="px-5 pt-5 pb-2 flex items-start justify-between gap-3">
            <div>
              <p className="text-[10px] font-black text-ink-3 mb-0.5">Fechamento mensal</p>
              <h2 className="text-ink-1 font-bold text-xl">{data?.month_label ?? 'Mês passado'}</h2>
            </div>
            <button
              onClick={failed ? onClose : handleClose}
              aria-label="Fechar"
              className="w-8 h-8 flex items-center justify-center rounded-full border border-line text-ink-3 hover:text-ink-1 transition-colors shrink-0"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
          <p className="px-5 pb-5 text-sm text-ink-2 leading-relaxed">
            {failed
              ? 'Não foi possível carregar seu fechamento agora. Ele continua no sino, tente de novo em instantes.'
              : 'Você não seguiu nenhum pick nesse mês, então não há fechamento pra confirmar.'}
          </p>
          <div className="px-5 pb-6">
            <button onClick={failed ? onClose : handleClose} className="btn-ghost w-full py-3 text-sm">
              Fechar
            </button>
          </div>
        </motion.div>
      </motion.div>
    )
  }

  const readOnly  = data.already_closed
  const isProfit  = data.total_pnl >= 0
  const pnlAbs    = Math.abs(data.total_pnl)
  const ganhoU    = data.unit_value > 0 ? data.total_pnl / data.unit_value : 0
  const winRate   = data.total_resolved > 0 ? Math.round(data.greens / data.total_resolved * 100) : 0
  const paidPlan  = data.paid_plan
  const accent    = isProfit ? 'text-green-400' : 'text-red-400'
  const accentBg  = isProfit ? 'bg-green-500/10 border-green-500/20' : 'bg-red-500/10 border-red-500/20'
  const bancaInicio = data.bankroll_current - data.total_pnl

  const distTotal = data.greens + data.reds + data.push + data.half_wins + data.half_loss
  const distItems = [
    { label: 'GREEN',  value: data.greens,   color: 'bg-green-500' },
    { label: 'RED',    value: data.reds,      color: 'bg-red-500'  },
    { label: '½ WIN',  value: data.half_wins, color: 'bg-teal-500' },
    { label: '½ LOSS', value: data.half_loss, color: 'bg-orange-500' },
    { label: 'PUSH',   value: data.push,      color: 'bg-ink-4' },
  ].filter(d => d.value > 0)

  return (
    <motion.div
      variants={backdropFade} initial="hidden" animate="visible" exit="exit"
      className="fixed inset-0 bg-black/90 backdrop-blur-sm z-[9998] flex items-end sm:items-center justify-center"
    >
      <motion.div variants={sheetUp} className="bg-surface-0 border border-line rounded-t-2xl sm:rounded-lg w-full sm:max-w-sm shadow-2xl overflow-y-auto max-h-[92dvh]">

        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-5 pb-3">
          <div className="flex items-center gap-2">
            {step === 'edit' && (
              <button
                onClick={() => setStep('summary')}
                className="w-7 h-7 flex items-center justify-center rounded-full text-ink-3 hover:text-ink-1 transition-colors"
              >
                <ArrowLeft className="w-4 h-4" />
              </button>
            )}
            <div>
              <p className="text-[10px] font-black text-ink-3 mb-0.5">
                {step === 'edit' ? 'Atualizar banca' : step === 'success' ? 'Banca atualizada' : 'Fechamento mensal'}
              </p>
              <h2 className="text-ink-1 font-bold text-xl">
                {step === 'success' ? fmtBRL(savedValue) : data.month_label}
              </h2>
            </div>
          </div>
          {step !== 'edit' && (
            <button
              onClick={handleClose}
              className="w-8 h-8 flex items-center justify-center rounded-full border border-line text-ink-3 hover:text-ink-1 hover:border-line-strong transition-colors shrink-0"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>

        <AnimatePresence mode="wait">
        {/* ── STEP: SUMMARY ── */}
        {step === 'summary' && (
          <motion.div key="summary" variants={tabFade} initial="hidden" animate="visible" exit="exit">
            {/* Bloco P&L */}
            <div className={`mx-5 rounded-lg px-4 py-4 mb-3 border ${accentBg}`}>
              <div className={`flex items-center gap-2 mb-1 ${accent}`}>
                {isProfit ? <TrendingUp className="w-5 h-5 shrink-0" /> : <TrendingDown className="w-5 h-5 shrink-0" />}
                <span className="text-[28px] leading-tight font-black break-all">
                  {isProfit ? '+' : '−'}{fmtBRL(pnlAbs)}
                </span>
              </div>
              <p className={`text-sm font-black ml-7 mb-3 ${accent} opacity-75`}>
                {ganhoU >= 0 ? '+' : ''}{ganhoU.toFixed(1)} unidades
                <span className="text-ink-4 font-normal ml-1">(1u = {fmtBRL(data.unit_value)})</span>
              </p>
              <div className="flex items-center justify-between pt-2 border-t border-line">
                <span className="text-[11px] text-ink-3">
                  {data.greens}G, {data.reds}R
                  {data.half_wins > 0 ? `, ${data.half_wins}½W` : ''}
                  {data.half_loss > 0 ? `, ${data.half_loss}½L` : ''}
                  {data.push > 0 ? `, ${data.push}P` : ''}
                  {' '}, {data.total_resolved} picks
                </span>
                <span className={`text-[11px] font-bold ${winRate >= 55 ? 'text-green-400' : 'text-ink-2'}`}>
                  {winRate}% win rate
                </span>
              </div>
            </div>

            {/* Banca início e fim */}
            <div className="mx-5 mb-3 flex items-center gap-3 bg-surface-1 rounded-lg border border-line px-4 py-3">
              <div className="flex-1 min-w-0">
                <p className="text-[10px] text-ink-3 mb-0.5">Início do mês</p>
                <p className="text-sm font-black text-ink-2 truncate">{fmtBRL(bancaInicio)}</p>
              </div>
              <div className={`w-6 h-px shrink-0 ${isProfit ? 'bg-green-500/50' : 'bg-red-500/50'}`} />
              <div className="flex-1 min-w-0 text-right">
                <p className="text-[10px] text-ink-3 mb-0.5">Fim do mês</p>
                <p className={`text-sm font-black truncate ${accent}`}>{fmtBRL(data.bankroll_current)}</p>
              </div>
            </div>

            {/* Assinatura paga */}
            {paidPlan && (
              <div className="mx-5 mb-3 bg-green-500/10 border border-green-500/20 rounded-lg px-4 py-3 flex items-center gap-3">
                <BadgeCheck className="w-5 h-5 shrink-0 text-green-400" />
                <p className="text-sm font-black text-green-300 leading-snug">
                  Esse mês você já pagou sua assinatura do Pick IA com o lucro
                </p>
              </div>
            )}

            {/* Alavancagem · só caminho encerrado virou dinheiro. O que está em
                andamento aparece à parte porque ainda está todo em jogo. */}
            {data.alavancagem?.configured && (
              <div className="mx-5 mb-3 bg-surface-1 rounded-lg border border-line px-4 py-3">
                <p className="text-[10px] text-ink-3 mb-1.5">Alavancagem</p>
                <div className="flex items-center justify-between">
                  <span className={`text-sm font-black ${data.alavancagem.realized_this_month >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {data.alavancagem.realized_this_month >= 0 ? '+' : ''}{fmtBRL(data.alavancagem.realized_this_month)}
                  </span>
                  <span className="text-[11px] text-ink-3">
                    {data.alavancagem.closed_this_month} {data.alavancagem.closed_this_month === 1 ? 'caminho encerrado' : 'caminhos encerrados'}
                  </span>
                </div>
                {data.alavancagem.busted_this_month && (
                  <p className="text-[11px] text-orange-400 font-semibold mt-1">
                    Um caminho estourou esse mês, e perdeu só o valor de entrada
                  </p>
                )}
                <p className="text-[11px] text-ink-4 mt-1">
                  Em andamento: {fmtBRL(data.alavancagem.current_bankroll)} , ainda não conta como dinheiro
                </p>
              </div>
            )}

            {/* Distribuição */}
            {distTotal > 0 && (
              <div className="mx-5 mb-4">
                <div className="flex h-1.5 rounded-full overflow-hidden gap-px">
                  {distItems.map(d => (
                    <div key={d.label} className={d.color} style={{ width: `${Math.round(d.value / distTotal * 100)}%` }} />
                  ))}
                </div>
                <div className="flex gap-3 mt-1.5 flex-wrap">
                  {distItems.map(d => (
                    <span key={d.label} className="text-[10px] text-ink-3 font-semibold">{d.label} {d.value}</span>
                  ))}
                </div>
              </div>
            )}

            {/* Ações */}
            <div className="px-5 pb-6 space-y-2">
              <button
                onClick={() => handleShare(data)}
                className="btn-ghost w-full py-3 text-sm flex items-center justify-center gap-2"
              >
                {copied ? <Check className="w-4 h-4 shrink-0 text-green-400" /> : <Share2 className="w-4 h-4 shrink-0" />}
                {copied ? 'Copiado!' : 'Compartilhar resultado'}
              </button>

              {/* Já confirmado (aqui ou em outro aparelho): vira consulta. Reabrir a
                  edição sobrescreveria o registro histórico do mês. */}
              {readOnly ? (
                <>
                  <div className="flex items-center gap-2 justify-center text-ink-3 text-xs font-semibold py-1">
                    <Check className="w-4 h-4 shrink-0 text-accent-ink" />
                    Banca já atualizada para esse fechamento
                  </div>
                  <button onClick={handleClose} className="btn-ghost w-full py-3 text-sm">
                    Fechar
                  </button>
                </>
              ) : (
                <>
                  {/* Atualizar com o lucro · salva direto */}
                  <button
                    onClick={handleUpdateDirect}
                    disabled={saving}
                    className="btn-primary w-full py-3 text-sm flex items-center justify-center gap-2 disabled:opacity-50"
                  >
                    {saving
                      ? 'Atualizando...'
                      : <><span className="truncate">Atualizar banca para {fmtBRL(data.bankroll_current)}</span><ChevronRight className="w-4 h-4 shrink-0" /></>
                    }
                  </button>

                  {/* Definir outro valor · abre input */}
                  <button
                    onClick={() => { setNewBanca(''); setStep('edit') }}
                    className="btn-ghost w-full py-3 text-sm flex items-center justify-center gap-2"
                  >
                    Definir outro valor de banca
                    <ChevronRight className="w-4 h-4 shrink-0" />
                  </button>

                  <button
                    onClick={handleClose}
                    className="w-full py-2.5 text-ink-4 hover:text-ink-2 text-sm font-semibold transition-colors"
                  >
                    Fechar sem alterar
                  </button>
                </>
              )}
            </div>
          </motion.div>
        )}

        {/* ── STEP: EDIT ── */}
        {step === 'edit' && (
          <motion.div key="edit" variants={tabFade} initial="hidden" animate="visible" exit="exit" className="px-5 pb-6 pt-1 space-y-3">
            <p className="text-sm text-ink-2 leading-snug">
              Confirme o valor que será a sua nova banca de entrada para o próximo mês.
            </p>

            {/* Input de valor */}
            <div className="flex items-center bg-surface-1 border border-line-strong rounded-lg px-4 py-3.5 gap-2 focus-within:border-ink-4 transition-colors">
              <span className="text-ink-2 font-black text-lg shrink-0">R$</span>
              <input
                ref={inputRef}
                type="text"
                inputMode="decimal"
                placeholder="0,00"
                value={newBanca}
                onChange={e => setNewBanca(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSave()}
                className="flex-1 bg-transparent text-ink-1 font-black text-2xl outline-none placeholder:text-ink-4"
              />
            </div>

            <button
              onClick={handleSave}
              disabled={saving || !newBanca || parseBanca() <= 0}
              className="btn-primary w-full py-3.5 text-sm font-black disabled:opacity-40"
            >
              {saving ? 'Salvando...' : 'Confirmar'}
            </button>

            <button
              onClick={() => setStep('summary')}
              className="btn-ghost w-full py-3 text-sm"
            >
              Voltar
            </button>
          </motion.div>
        )}

        {/* ── STEP: SUCCESS ── */}
        {step === 'success' && (
          <motion.div key="success" variants={tabFade} initial="hidden" animate="visible" exit="exit" className="px-5 pb-10 pt-2 flex flex-col items-center text-center gap-4">
            <motion.div
              initial={{ scale: 0.5, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ type: 'spring', stiffness: 400, damping: 20 }}
              className="w-20 h-20 rounded-full bg-green-500/10 border border-green-500/20 flex items-center justify-center"
            >
              <Check className="w-9 h-9 text-green-400" />
            </motion.div>
            <div>
              <p className="text-ink-1 font-black text-2xl mb-1">{fmtBRL(savedValue)}</p>
              <p className="text-ink-2 text-sm">Nova banca definida com sucesso</p>
            </div>
          </motion.div>
        )}
        </AnimatePresence>
      </motion.div>
    </motion.div>
  )
}
