import { useEffect, useRef, useState } from 'react'
import { TrendingUp, TrendingDown, X, BadgeCheck, Share2, Check, ChevronRight, ArrowLeft } from 'lucide-react'
import api from '../services/api'
import { fmtBRL } from '../utils/format'

function getLastMonthKey(): string {
  const now = new Date()
  const y = now.getMonth() === 0 ? now.getFullYear() - 1 : now.getFullYear()
  const m = now.getMonth() === 0 ? 12 : now.getMonth()
  return `${y}-${String(m).padStart(2, '0')}`
}

const LS_KEY = 'pickia_monthly_close'

export function shouldShowMonthlyClose(): boolean {
  return localStorage.getItem(LS_KEY) !== getLastMonthKey()
}

export function dismissMonthlyClose() {
  localStorage.setItem(LS_KEY, getLastMonthKey())
}

interface AlavancagemMonthData {
  configured: boolean
  current_bankroll: number
  initial_bankroll: number
  greens_this_month: number
  reds_this_month: number
  busted_this_month: boolean
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
    greens_this_month: 3,
    reds_this_month: 1,
    busted_this_month: true,
  },
  already_closed: false,
}

type Step = 'summary' | 'edit' | 'success'

interface Props {
  onClose: () => void
}

export default function MonthlyCloseModal({ onClose }: Props) {
  const isPreview = new URLSearchParams(window.location.search).get('preview') === 'monthly'

  const [data, setData]       = useState<CloseData | null>(isPreview ? MOCK_DATA : null)
  const [loading, setLoading] = useState(!isPreview)
  const [step, setStep]       = useState<Step>('summary')
  const [newBanca, setNewBanca] = useState('')
  const [saving, setSaving]   = useState(false)
  const [savedValue, setSavedValue] = useState(0)
  const [copied, setCopied]   = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (isPreview) return
    api.get('/banca/monthly-close')
      .then(r => {
        // Já fechado em outro dispositivo/sessão neste mês — não reabre o popup
        // nem arrisca sobrescrever o registro histórico com uma nova confirmação.
        if (r.data.already_closed) { dismissMonthlyClose(); onClose(); return }
        setData(r.data)
      })
      .catch(() => { dismissMonthlyClose(); onClose() })
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

  const handleClose = () => { dismissMonthlyClose(); onClose() }

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
        bankroll_goal: null,
        unit_value: data.unit_value,
        monthly_close_month_key: data.month_key,
      })
      setSavedValue(data.bankroll_current)
      setStep('success')
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
        bankroll_goal: null,
        unit_value: data.unit_value,
        monthly_close_month_key: data.month_key,
      })
      setSavedValue(value)
      setStep('success')
    } catch { }
    finally { setSaving(false) }
  }

  const handleShare = async (d: CloseData) => {
    const ganhoU = d.unit_value > 0 ? d.total_pnl / d.unit_value : 0
    const isProfit = d.total_pnl >= 0
    const text = [
      `Fechamento de ${d.month_label} na Pick IA`,
      `${isProfit ? '+' : '-'}${fmtBRL(Math.abs(d.total_pnl))} (${ganhoU >= 0 ? '+' : ''}${ganhoU.toFixed(1)}u)`,
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

  const hasAlavActivity = !!data?.alavancagem && (data.alavancagem.greens_this_month > 0 || data.alavancagem.reds_this_month > 0)
  if (!data || (data.total_followed === 0 && !hasAlavActivity)) {
    dismissMonthlyClose()
    onClose()
    return null
  }

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
    { label: 'PUSH',   value: data.push,      color: 'bg-zinc-500' },
  ].filter(d => d.value > 0)

  return (
    <div className="fixed inset-0 bg-black/90 backdrop-blur-sm z-[9998] flex items-end sm:items-center justify-center">
      <div className="bg-zinc-950 border border-zinc-800 rounded-t-2xl sm:rounded-2xl w-full sm:max-w-sm shadow-2xl overflow-y-auto max-h-[92dvh]">

        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-5 pb-3">
          <div className="flex items-center gap-2">
            {step === 'edit' && (
              <button
                onClick={() => setStep('summary')}
                className="w-7 h-7 flex items-center justify-center rounded-full text-zinc-500 hover:text-white transition-colors"
              >
                <ArrowLeft className="w-4 h-4" />
              </button>
            )}
            <div>
              <p className="text-[10px] font-black text-zinc-500 uppercase tracking-widest mb-0.5">
                {step === 'edit' ? 'Atualizar banca' : step === 'success' ? 'Banca atualizada' : 'Fechamento mensal'}
              </p>
              <h2 className="text-white font-black text-xl">
                {step === 'success' ? fmtBRL(savedValue) : data.month_label}
              </h2>
            </div>
          </div>
          {step !== 'edit' && (
            <button
              onClick={handleClose}
              className="w-8 h-8 flex items-center justify-center rounded-full border border-zinc-800 text-zinc-500 hover:text-white hover:border-zinc-600 transition-colors shrink-0"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* ── STEP: SUMMARY ── */}
        {step === 'summary' && (
          <>
            {/* Bloco P&L */}
            <div className={`mx-5 rounded-xl px-4 py-4 mb-3 border ${accentBg}`}>
              <div className={`flex items-center gap-2 mb-1 ${accent}`}>
                {isProfit ? <TrendingUp className="w-5 h-5 shrink-0" /> : <TrendingDown className="w-5 h-5 shrink-0" />}
                <span className="text-[28px] leading-tight font-black break-all">
                  {isProfit ? '+' : '−'}{fmtBRL(pnlAbs)}
                </span>
              </div>
              <p className={`text-sm font-black ml-7 mb-3 ${accent} opacity-75`}>
                {ganhoU >= 0 ? '+' : ''}{ganhoU.toFixed(1)} unidades
                <span className="text-zinc-600 font-normal ml-1">(1u = {fmtBRL(data.unit_value)})</span>
              </p>
              <div className="flex items-center justify-between pt-2 border-t border-white/5">
                <span className="text-[11px] text-zinc-500">
                  {data.greens}G · {data.reds}R
                  {data.half_wins > 0 ? ` · ${data.half_wins}½W` : ''}
                  {data.half_loss > 0 ? ` · ${data.half_loss}½L` : ''}
                  {data.push > 0 ? ` · ${data.push}P` : ''}
                  {' '}· {data.total_resolved} picks
                </span>
                <span className={`text-[11px] font-bold ${winRate >= 55 ? 'text-green-400' : 'text-zinc-400'}`}>
                  {winRate}% win rate
                </span>
              </div>
            </div>

            {/* Banca início → fim */}
            <div className="mx-5 mb-3 flex items-center gap-3 bg-zinc-900 rounded-xl border border-zinc-800 px-4 py-3">
              <div className="flex-1 min-w-0">
                <p className="text-[10px] text-zinc-500 uppercase tracking-wider mb-0.5">Início do mês</p>
                <p className="text-sm font-black text-zinc-300 truncate">{fmtBRL(bancaInicio)}</p>
              </div>
              <div className={`w-6 h-px shrink-0 ${isProfit ? 'bg-green-500/50' : 'bg-red-500/50'}`} />
              <div className="flex-1 min-w-0 text-right">
                <p className="text-[10px] text-zinc-500 uppercase tracking-wider mb-0.5">Fim do mês</p>
                <p className={`text-sm font-black truncate ${accent}`}>{fmtBRL(data.bankroll_current)}</p>
              </div>
            </div>

            {/* Assinatura paga */}
            {paidPlan && (
              <div className="mx-5 mb-3 bg-green-500/10 border border-green-500/20 rounded-xl px-4 py-3 flex items-center gap-3">
                <BadgeCheck className="w-5 h-5 shrink-0 text-green-400" />
                <p className="text-sm font-black text-green-300 leading-snug">
                  Esse mês você já pagou sua assinatura do Pick IA com o lucro
                </p>
              </div>
            )}

            {/* Alavancagem — série é composta, não entra na banca de unidades acima */}
            {data.alavancagem?.configured && (
              <div className="mx-5 mb-3 bg-zinc-900 rounded-xl border border-zinc-800 px-4 py-3">
                <p className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1.5">Série de alavancagem</p>
                <div className="flex items-center justify-between">
                  <span className="text-sm font-black text-white">{fmtBRL(data.alavancagem.current_bankroll)}</span>
                  <span className="text-[11px] text-zinc-500">
                    {data.alavancagem.greens_this_month}G · {data.alavancagem.reds_this_month}R no mês
                  </span>
                </div>
                {data.alavancagem.busted_this_month && (
                  <p className="text-[11px] text-orange-400 font-semibold mt-1">
                    Série resetou pra {fmtBRL(data.alavancagem.initial_bankroll)} esse mês
                  </p>
                )}
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
                    <span key={d.label} className="text-[10px] text-zinc-500 font-semibold">{d.label} {d.value}</span>
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

              {/* Atualizar com o lucro — salva direto */}
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

              {/* Definir outro valor — abre input */}
              <button
                onClick={() => { setNewBanca(''); setStep('edit') }}
                className="btn-ghost w-full py-3 text-sm flex items-center justify-center gap-2"
              >
                Definir outro valor de banca
                <ChevronRight className="w-4 h-4 shrink-0" />
              </button>

              <button
                onClick={handleClose}
                className="w-full py-2.5 text-zinc-600 hover:text-zinc-400 text-sm font-semibold transition-colors"
              >
                Fechar sem alterar
              </button>
            </div>
          </>
        )}

        {/* ── STEP: EDIT ── */}
        {step === 'edit' && (
          <div className="px-5 pb-6 pt-1 space-y-3">
            <p className="text-sm text-zinc-400 leading-snug">
              Confirme o valor que será a sua nova banca de entrada para o próximo mês.
            </p>

            {/* Input de valor */}
            <div className="flex items-center bg-zinc-900 border border-zinc-700 rounded-xl px-4 py-3.5 gap-2 focus-within:border-zinc-500 transition-colors">
              <span className="text-zinc-400 font-black text-lg shrink-0">R$</span>
              <input
                ref={inputRef}
                type="text"
                inputMode="decimal"
                placeholder="0,00"
                value={newBanca}
                onChange={e => setNewBanca(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSave()}
                className="flex-1 bg-transparent text-white font-black text-2xl outline-none placeholder:text-zinc-700"
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
          </div>
        )}

        {/* ── STEP: SUCCESS ── */}
        {step === 'success' && (
          <div className="px-5 pb-10 pt-2 flex flex-col items-center text-center gap-4">
            <div className="w-20 h-20 rounded-full bg-green-500/10 border border-green-500/20 flex items-center justify-center">
              <Check className="w-9 h-9 text-green-400" />
            </div>
            <div>
              <p className="text-white font-black text-2xl mb-1">{fmtBRL(savedValue)}</p>
              <p className="text-zinc-400 text-sm">Nova banca definida com sucesso</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
