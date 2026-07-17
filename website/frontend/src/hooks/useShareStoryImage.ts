import { useState } from 'react'
import api from '../services/api'
import {
  buildStoryImage, StoryImageInput,
  buildResultsStoryImage, ResultsStoryInput,
  buildTodayGamesStoryImage, TodayGameItem,
} from '../utils/shareStoryImage'
import { winRate as calcWinRate } from '../utils/format'

export type SharePickInput = Omit<StoryImageInput, 'shareUrl'> & {
  pickId: number
  /** vip | free | multipla | alavancagem · normalizado para a rota pública /p/:tipo/:id */
  pickTypeRoute: string
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 5000)
}

/** Dispara o share nativo (com arquivo, se suportado) ou baixa a imagem + copia/compartilha o link. */
async function dispatchShare(blob: Blob, filename: string, title: string, text: string, shareUrl: string) {
  const file = new File([blob], filename, { type: 'image/png' })
  const canShareFiles = typeof navigator.share === 'function'
    && typeof navigator.canShare === 'function'
    && navigator.canShare({ files: [file] })

  if (canShareFiles) {
    await navigator.share({ title, text, url: shareUrl, files: [file] })
  } else if (navigator.share) {
    downloadBlob(blob, filename)
    await navigator.share({ title, text, url: shareUrl })
  } else {
    downloadBlob(blob, filename)
    await navigator.clipboard.writeText(shareUrl)
  }
}

async function getReferralCode(): Promise<string> {
  try {
    const r = await api.get('/auth/referral')
    return r.data?.referral_code ?? ''
  } catch {
    return ''
  }
}

export function useShareStoryImage() {
  const [sharing, setSharing] = useState(false)
  const [shared, setShared] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const share = async (input: SharePickInput) => {
    setSharing(true)
    setError(null)
    try {
      const [refResult, statsResult] = await Promise.allSettled([
        api.get('/auth/referral'),
        api.get('/public/results'),
      ])
      const refCode = refResult.status === 'fulfilled' ? (refResult.value.data?.referral_code ?? '') : ''
      const summary = statsResult.status === 'fulfilled' ? statsResult.value.data?.summary : null
      const winRatePct = summary ? calcWinRate(summary.greens ?? 0, summary.total ?? 0) : null

      const shareUrl = `${window.location.origin}/p/${input.pickTypeRoute}/${input.pickId}${refCode ? `?ref=${refCode}` : ''}`
      const blob = await buildStoryImage({ ...input, shareUrl, winRatePct })
      const resultLabel = input.result ? ` · ${input.result}` : ''
      const text = `Pick IA${resultLabel}: ${input.homeTeamName}${input.awayTeamName ? ` x ${input.awayTeamName}` : ''} @ ${input.odd.toFixed(2)}`

      await dispatchShare(blob, 'pick-ia.png', 'Pick IA', text, shareUrl)
      setShared(true)
      setTimeout(() => setShared(false), 2500)
    } catch (err: any) {
      if (err?.name !== 'AbortError') {
        setError('Não foi possível gerar a imagem. Tente novamente.')
      }
    } finally {
      setSharing(false)
    }
  }

  return { share, sharing, shared, error }
}

/** Compartilha o card de resultado geral da IA (win rate, picks, lucro). */
export function useShareResultsImage() {
  const [sharing, setSharing] = useState(false)
  const [shared, setShared] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const share = async (input: Omit<ResultsStoryInput, 'shareUrl'>) => {
    setSharing(true)
    setError(null)
    try {
      const refCode = await getReferralCode()
      const shareUrl = `${window.location.origin}/resultados${refCode ? `?ref=${refCode}` : ''}`
      const blob = await buildResultsStoryImage({ ...input, shareUrl })
      const text = `A IA da Pick IA acerta ${Math.round(input.winRatePct)}% dos picks. Histórico 100% auditável.`
      await dispatchShare(blob, 'pick-ia-resultados.png', 'Pick IA · Resultados', text, shareUrl)
      setShared(true)
      setTimeout(() => setShared(false), 2500)
    } catch (err: any) {
      if (err?.name !== 'AbortError') {
        setError('Não foi possível gerar a imagem. Tente novamente.')
      }
    } finally {
      setSharing(false)
    }
  }

  return { share, sharing, shared, error }
}

/** Compartilha os jogos de hoje que a IA vai analisar (antes dos resultados sairem). */
export function useShareTodayGamesImage() {
  const [sharing, setSharing] = useState(false)
  const [shared, setShared] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const share = async (games: TodayGameItem[]) => {
    setSharing(true)
    setError(null)
    try {
      const refCode = await getReferralCode()
      const shareUrl = `${window.location.origin}/${refCode ? `?ref=${refCode}` : ''}`
      const blob = await buildTodayGamesStoryImage({ games, shareUrl })
      const text = `A IA da Pick IA vai analisar ${games.length} jogo(s) hoje. Vem ver.`
      await dispatchShare(blob, 'pick-ia-jogos-hoje.png', 'Pick IA · Jogos de hoje', text, shareUrl)
      setShared(true)
      setTimeout(() => setShared(false), 2500)
    } catch (err: any) {
      if (err?.name !== 'AbortError') {
        setError('Não foi possível gerar a imagem. Tente novamente.')
      }
    } finally {
      setSharing(false)
    }
  }

  return { share, sharing, shared, error }
}
