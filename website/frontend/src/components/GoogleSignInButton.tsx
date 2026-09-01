import { useEffect, useRef, useState } from 'react'
import api from '../services/api'

interface CodeClient {
  requestCode: () => void
}

declare global {
  interface Window {
    google?: {
      accounts: {
        oauth2: {
          initCodeClient: (config: Record<string, unknown>) => CodeClient
        }
      }
    }
  }
}

const SCRIPT_SRC = 'https://accounts.google.com/gsi/client'
let scriptPromise: Promise<void> | null = null

function loadScript(): Promise<void> {
  if (window.google?.accounts?.oauth2) return Promise.resolve()
  if (scriptPromise) return scriptPromise
  scriptPromise = new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = SCRIPT_SRC
    s.async = true
    s.defer = true
    s.onload = () => resolve()
    s.onerror = () => {
      scriptPromise = null
      reject(new Error('Falha ao carregar o login do Google'))
    }
    document.head.appendChild(s)
  })
  return scriptPromise
}

/* O client_id vem do backend, não de uma VITE_ do build · ligar o Google passa
   a ser variável de servidor, sem rebuild do front. E o servidor só o devolve
   quando o par client_id + secret existe: sem os dois, o fluxo de código não
   fecha e um botão aqui só levaria a pessoa a escolher a conta para falhar
   depois. Promessa memorizada no módulo porque a tela remonta este componente
   a cada troca entre "entrar" e "criar conta". */
interface ConfigGoogle { clientId: string; scope: string }

let configPromise: Promise<ConfigGoogle> | null = null
function fetchConfig(): Promise<ConfigGoogle> {
  if (!configPromise) {
    configPromise = api.get('/auth/google/config')
      .then(r => ({
        clientId: String(r.data?.client_id ?? ''),
        // O escopo vem do servidor porque ele pode incluir o telefone, e essa
        // é uma decisão que muda no painel do Railway · não no build do front.
        scope: String(r.data?.scope ?? 'openid email profile'),
      }))
      .catch(() => {
        configPromise = null
        return { clientId: '', scope: 'openid email profile' }
      })
  }
  return configPromise
}

/* O "G" oficial. É o único elemento de marca que o Google exige preservar, e
   ele proíbe recolorir · por isso as cores estão fixas aqui, e não em token do
   tema. O resto do botão é nosso e segue o design system. */
function LogoGoogle() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" className="shrink-0">
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62Z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18Z" />
      <path fill="#FBBC05" d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1l3.01-2.33Z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58Z" />
    </svg>
  )
}

interface Props {
  /** Recebe o código de autorização. Quem o troca por token é o backend. */
  onCode: (code: string) => void
  /** Avisa a tela se o botão existe · é o que decide mostrar o separador "ou". */
  onDisponivel?: (disponivel: boolean) => void
  /** Muda só o verbo do rótulo. */
  modo?: 'login' | 'register'
  desabilitado?: boolean
}

/* Botão de entrar com Google, desenhado aqui.
   O widget oficial do Google vive num iframe e não aceita CSS de fora: vinha
   com Roboto, altura própria e um quadrado branco atrás do logo, tudo destoando
   do resto da tela. Usando o fluxo de código de autorização (initCodeClient), o
   Google só precisa abrir o popup · o botão que dispara isso pode ser nosso.
   Some por completo quando o servidor não tem o Google configurado, igual ao
   Turnstile. */
export default function GoogleSignInButton({ onCode, onDisponivel, modo = 'login', desabilitado }: Props) {
  const [pronto, setPronto] = useState(false)
  const clientRef = useRef<CodeClient | null>(null)
  const avisaRef = useRef(onDisponivel)
  avisaRef.current = onDisponivel
  // O callback é registrado uma vez e sobrevive a re-renders; sem a ref, ele
  // fecharia sobre o `onCode` da primeira montagem.
  const cbRef = useRef(onCode)
  cbRef.current = onCode

  useEffect(() => {
    let cancelado = false

    Promise.all([fetchConfig(), loadScript()])
      .then(([{ clientId, scope }]) => {
        if (cancelado) return
        if (!clientId || !window.google?.accounts?.oauth2) {
          avisaRef.current?.(false)
          return
        }
        clientRef.current = window.google.accounts.oauth2.initCodeClient({
          client_id: clientId,
          scope,
          ux_mode: 'popup',
          callback: (resposta: { code?: string }) => {
            if (resposta?.code) cbRef.current(resposta.code)
          },
        })
        setPronto(true)
        avisaRef.current?.(true)
      })
      .catch(() => {
        // Silencioso de propósito: o Google fora do ar não é problema de quem
        // ia entrar com senha, e um alerta vermelho aqui só assustaria.
        if (cancelado) return
        avisaRef.current?.(false)
      })

    return () => { cancelado = true }
  }, [])

  if (!pronto) return null

  return (
    <button
      type="button"
      onClick={() => clientRef.current?.requestCode()}
      disabled={desabilitado}
      className="w-full flex items-center justify-center gap-3 rounded-lg border border-line-strong bg-surface-2 hover:bg-surface-3 disabled:opacity-60 disabled:cursor-not-allowed text-ink-1 text-sm font-bold py-3 min-h-[48px] transition-colors"
    >
      <LogoGoogle />
      {modo === 'register' ? 'Criar conta com o Google' : 'Continuar com o Google'}
    </button>
  )
}
