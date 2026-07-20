import { useEffect, useRef, forwardRef, useImperativeHandle } from 'react'
import { TURNSTILE_SITE_KEY } from '../config'

declare global {
  interface Window {
    turnstile?: {
      render: (container: HTMLElement, options: Record<string, unknown>) => string
      reset: (widgetId?: string) => void
      remove: (widgetId?: string) => void
    }
  }
}

const SCRIPT_SRC = 'https://challenges.cloudflare.com/turnstile/v0/api.js'
let scriptPromise: Promise<void> | null = null

function loadScript(): Promise<void> {
  if (window.turnstile) return Promise.resolve()
  if (scriptPromise) return scriptPromise
  scriptPromise = new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = SCRIPT_SRC
    s.async = true
    s.defer = true
    s.onload = () => resolve()
    s.onerror = () => reject(new Error('Falha ao carregar verificação de segurança'))
    document.head.appendChild(s)
  })
  return scriptPromise
}

export interface TurnstileHandle {
  reset: () => void
}

interface TurnstileProps {
  onVerify: (token: string) => void
}

// Widget de verificação anti-bot (Cloudflare Turnstile). Fica invisível/no-op
// se VITE_TURNSTILE_SITE_KEY não estiver configurada (dev sem chave real) --
// o backend segue o mesmo padrão, pula a verificação se TURNSTILE_SECRET_KEY
// não estiver setada no servidor.
const Turnstile = forwardRef<TurnstileHandle, TurnstileProps>(({ onVerify }, ref) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const widgetId = useRef<string | null>(null)

  useImperativeHandle(ref, () => ({
    reset: () => {
      if (widgetId.current && window.turnstile) window.turnstile.reset(widgetId.current)
    },
  }))

  useEffect(() => {
    if (!TURNSTILE_SITE_KEY) return
    let cancelled = false
    loadScript()
      .then(() => {
        if (cancelled || !containerRef.current || !window.turnstile) return
        widgetId.current = window.turnstile.render(containerRef.current, {
          sitekey: TURNSTILE_SITE_KEY,
          theme: 'dark',
          callback: (token: string) => onVerify(token),
          'expired-callback': () => onVerify(''),
          'error-callback': () => onVerify(''),
        })
      })
      .catch(() => {})
    return () => {
      cancelled = true
      if (widgetId.current && window.turnstile) window.turnstile.remove(widgetId.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (!TURNSTILE_SITE_KEY) return null
  return <div ref={containerRef} className="flex justify-center" />
})
Turnstile.displayName = 'Turnstile'

export default Turnstile
