import { useState } from 'react'
import api from '../services/api'
import { buildStoryImage, StoryImageInput } from '../utils/shareStoryImage'

export type SharePickInput = Omit<StoryImageInput, 'shareUrl'> & {
  pickId: number
  /** vip | free | multipla | alavancagem — normalizado para a rota pública /p/:tipo/:id */
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

export function useShareStoryImage() {
  const [sharing, setSharing] = useState(false)
  const [shared, setShared] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const share = async (input: SharePickInput) => {
    setSharing(true)
    setError(null)
    try {
      let refCode = ''
      try {
        const r = await api.get('/auth/referral')
        refCode = r.data?.referral_code ?? ''
      } catch { /* sem ref code */ }

      const shareUrl = `${window.location.origin}/p/${input.pickTypeRoute}/${input.pickId}${refCode ? `?ref=${refCode}` : ''}`
      const blob = await buildStoryImage({ ...input, shareUrl })
      const file = new File([blob], 'pick-ia.png', { type: 'image/png' })
      const resultLabel = input.result ? ` · ${input.result}` : ''
      const text = `Pick IA${resultLabel}: ${input.homeTeamName}${input.awayTeamName ? ` x ${input.awayTeamName}` : ''} @ ${input.odd.toFixed(2)}`

      const canShareFiles = typeof navigator.share === 'function'
        && typeof navigator.canShare === 'function'
        && navigator.canShare({ files: [file] })

      if (canShareFiles) {
        await navigator.share({ title: 'Pick IA', text, url: shareUrl, files: [file] })
      } else if (navigator.share) {
        // Sem suporte a arquivo: compartilha só o link, mas ainda baixa a imagem pro usuário postar manualmente
        downloadBlob(blob, 'pick-ia.png')
        await navigator.share({ title: 'Pick IA', text, url: shareUrl })
      } else {
        downloadBlob(blob, 'pick-ia.png')
        await navigator.clipboard.writeText(shareUrl)
      }
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
