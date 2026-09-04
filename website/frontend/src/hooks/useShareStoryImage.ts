import { useState } from 'react'
import api from '../services/api'
import {
  buildStoryImage, StoryImageInput,
  buildResultsStoryImage, ResultsStoryInput,
  buildTodayGamesStoryImage, TodayGameItem,
  buildLeagueResultsStoryImage, LeagueResultItem,
  buildAlavancagemStoryImage, AlavancagemStoryInput,
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
    return
  }

  /*
   * SEM SHARE NATIVO, A IMAGEM BAIXADA É A ENTREGA · e ela vem primeiro.
   *
   * O caminho de desktop era `downloadBlob(...)` seguido de
   * `await navigator.clipboard.writeText(...)`, com o await propagando a
   * falha pro `catch` de quem chamou · que exibe "Não foi possível gerar a
   * imagem. Tente novamente.". A imagem tinha sido gerada e baixada; quem
   * falhou foi a área de transferência, que nega escrita fora de contexto
   * seguro, sem permissão ou com a aba em segundo plano. O usuário lia que o
   * compartilhamento não funcionou enquanto o PNG estava na pasta de
   * downloads.
   *
   * Copiar o link é conveniência, então nunca derruba o share.
   */
  downloadBlob(blob, filename)
  try {
    if (navigator.share) await navigator.share({ title, text, url: shareUrl })
    else await navigator.clipboard?.writeText(shareUrl)
  } catch (err: any) {
    // Cancelar a folha de compartilhamento é escolha do usuário · sobe pra
    // quem chamou não marcar "compartilhado". Falha de clipboard, não.
    if (err?.name === 'AbortError') throw err
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
      const resultLabel = input.result ? `, ${input.result}` : ''
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

  const share = async (input: Omit<ResultsStoryInput, 'shareUrl'> & { shareText?: string }) => {
    setSharing(true)
    setError(null)
    try {
      const refCode = await getReferralCode()
      const shareUrl = `${window.location.origin}/resultados${refCode ? `?ref=${refCode}` : ''}`
      const { shareText, ...imgInput } = input
      const blob = await buildResultsStoryImage({ ...imgInput, shareUrl })
      const text = shareText ?? `A IA da Pick IA acerta ${Math.round(input.winRatePct)}% dos picks. Histórico 100% auditável.`
      await dispatchShare(blob, 'pick-ia-resultados.png', 'Pick IA. Resultados', text, shareUrl)
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

/**
 * Compartilha os jogos que a IA vai analisar (ou já analisou) hoje/amanhã.
 * 'hoje': picks já saíram às 7h, texto no passado. 'amanha': prévia, picks
 * só saem no dia seguinte, texto no futuro.
 */
export function useShareTodayGamesImage() {
  const [sharing, setSharing] = useState(false)
  const [shared, setShared] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const share = async (games: TodayGameItem[], variant: 'hoje' | 'amanha' = 'hoje') => {
    setSharing(true)
    setError(null)
    try {
      const refCode = await getReferralCode()
      const shareUrl = `${window.location.origin}/${refCode ? `?ref=${refCode}` : ''}`
      const blob = await buildTodayGamesStoryImage({ games, shareUrl, variant })
      const text = variant === 'amanha'
        ? `A IA da Pick IA vai analisar ${games.length} jogo(s) amanhã. Os picks saem sem hora marcada, quando passam no corte.`
        : `A IA da Pick IA já analisou ${games.length} jogo(s) de hoje e os picks já estão no ar.`
      const filename = variant === 'amanha' ? 'pick-ia-jogos-amanha.png' : 'pick-ia-jogos-hoje.png'
      const title = variant === 'amanha' ? 'Pick IA. Jogos de amanhã' : 'Pick IA. Jogos de hoje'
      await dispatchShare(blob, filename, title, text, shareUrl)
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

/** Compartilha o resultado da IA quebrado por liga. */
export function useShareLeagueResultsImage() {
  const [sharing, setSharing] = useState(false)
  const [shared, setShared] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const share = async (leagues: LeagueResultItem[], badgeLabel?: string) => {
    setSharing(true)
    setError(null)
    try {
      const refCode = await getReferralCode()
      const shareUrl = `${window.location.origin}/resultados${refCode ? `?ref=${refCode}` : ''}`
      const blob = await buildLeagueResultsStoryImage({ leagues, shareUrl, badgeLabel })
      const top = leagues[0]
      const text = top
        ? `${top.leagueName}: ${Math.round(top.winRatePct)}% de acerto na Pick IA. Histórico 100% auditável.`
        : 'Resultados da IA por liga na Pick IA. Histórico 100% auditável.'
      await dispatchShare(blob, 'pick-ia-resultados-liga.png', 'Pick IA. Resultados por liga', text, shareUrl)
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

/**
 * Compartilha um BILHETE (múltipla ou Pick Boost) com as pernas uma a uma.
 *
 * Existe pelo mesmo motivo da alavancagem: o card de pick comum desenha UM
 * confronto, então uma múltipla de três saía por ali anunciando só a primeira
 * perna com a odd das três ao lado dela. Quem via lia uma aposta simples
 * pagando 3,20 e nem sabia dos outros dois jogos.
 *
 * O desenho é o mesmo dos três produtos combinados; o que muda é a cor, o selo
 * e o bloco de baixo (ver `composto` em buildAlavancagemStoryImage).
 */
export function useShareBilheteImage() {
  const [sharing, setSharing] = useState(false)
  const [shared, setShared] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const share = async (
    input: Omit<AlavancagemStoryInput, 'shareUrl'> & { pickId: number; pickTypeRoute: string },
  ) => {
    setSharing(true)
    setError(null)
    try {
      const refCode = await getReferralCode()
      const { pickId, pickTypeRoute, ...imgInput } = input
      const shareUrl = `${window.location.origin}/p/${pickTypeRoute}/${pickId}${refCode ? `?ref=${refCode}` : ''}`
      const blob = await buildAlavancagemStoryImage({ ...imgInput, shareUrl })
      const quantas = imgInput.legs.length
      const resultado = imgInput.result ? `, ${imgInput.result}` : ''
      const texto = `Pick IA${resultado}: bilhete de ${quantas} ${quantas === 1 ? 'seleção' : 'seleções'} a ${imgInput.oddCombined.toFixed(2)}.`
      await dispatchShare(blob, `pick-ia-${pickTypeRoute}.png`, 'Pick IA', texto, shareUrl)
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

/**
 * Compartilha um pick de alavancagem com as informações do produto: as pernas
 * uma a uma, o composto em unidades e o degrau do caminho.
 */
export function useShareAlavancagemImage() {
  const [sharing, setSharing] = useState(false)
  const [shared, setShared] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const share = async (
    input: Omit<AlavancagemStoryInput, 'shareUrl'> & { pickId: number },
  ) => {
    setSharing(true)
    setError(null)
    try {
      const refCode = await getReferralCode()
      const { pickId, ...imgInput } = input
      const shareUrl = `${window.location.origin}/p/alavancagem/${pickId}${refCode ? `?ref=${refCode}` : ''}`
      const blob = await buildAlavancagemStoryImage({ ...imgInput, shareUrl })
      const quantos = imgInput.legs.length
      const texto = `Alavancagem da Pick IA: ${quantos} ${quantos === 1 ? 'jogo' : 'jogos'}, 1 unidade virando ${imgInput.oddCombined.toFixed(2)}u.`
      await dispatchShare(blob, 'pick-ia-alavancagem.png', 'Pick IA. Alavancagem', texto, shareUrl)
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
