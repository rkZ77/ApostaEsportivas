import { useEffect, useRef, useState } from 'react'
import api from '../services/api'

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: Record<string, unknown>) => void
          renderButton: (container: HTMLElement, options: Record<string, unknown>) => void
          cancel: () => void
        }
      }
    }
  }
}

const SCRIPT_SRC = 'https://accounts.google.com/gsi/client'
let scriptPromise: Promise<void> | null = null

function loadScript(): Promise<void> {
  if (window.google?.accounts?.id) return Promise.resolve()
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
   a ser uma variável só, no servidor, sem rebuild do front. A promessa é
   memorizada no módulo porque a tela de login remonta este componente a cada
   troca entre "entrar" e "criar conta". */
let configPromise: Promise<string> | null = null
function fetchClientId(): Promise<string> {
  if (!configPromise) {
    configPromise = api.get('/auth/google/config')
      .then(r => String(r.data?.client_id ?? ''))
      .catch(() => {
        configPromise = null
        return ''
      })
  }
  return configPromise
}

interface Props {
  /** Recebe o ID token assinado pelo Google. Quem valida é o backend. */
  onCredential: (credential: string) => void
  /** Avisa a tela se o botão existe · é o que decide mostrar o separador "ou". */
  onDisponivel?: (disponivel: boolean) => void
  /** Muda só o rótulo do botão do Google ("Entrar com" vs "Inscreva-se com"). */
  modo?: 'login' | 'register'
}

/* Botão oficial do Google (Google Identity Services).
   Some por completo quando GOOGLE_CLIENT_ID não está configurado no servidor,
   igual ao Turnstile · em dev sem chave a tela continua inteira, só sem esta
   opção, em vez de mostrar um botão que sempre falha. */
export default function GoogleSignInButton({ onCredential, onDisponivel, modo = 'login' }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [pronto, setPronto] = useState(false)
  const avisaRef = useRef(onDisponivel)
  avisaRef.current = onDisponivel
  // O callback do Google é registrado uma vez e sobrevive a re-renders; sem a
  // ref, ele fecharia sobre o `onCredential` da primeira montagem.
  const cbRef = useRef(onCredential)
  cbRef.current = onCredential

  useEffect(() => {
    let cancelado = false

    Promise.all([fetchClientId(), loadScript().then(() => '')])
      .then(([clientId]) => {
        if (cancelado) return
        if (!clientId || !containerRef.current || !window.google) {
          avisaRef.current?.(false)
          return
        }

        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: (resposta: { credential?: string }) => {
            if (resposta?.credential) cbRef.current(resposta.credential)
          },
          // Sem One Tap: o pop-up automático aparecendo por cima do formulário
          // é o tipo de coisa que faz a pessoa fechar a aba. Aqui o Google só
          // entra quando ela clica no botão.
          auto_select: false,
          cancel_on_tap_outside: true,
          ux_mode: 'popup',
        })

        const largura = Math.min(
          Math.round(containerRef.current.getBoundingClientRect().width) || 320,
          400, // teto do próprio widget do Google
        )
        window.google.accounts.id.renderButton(containerRef.current, {
          type: 'standard',
          theme: document.documentElement.dataset.theme === 'light' ? 'outline' : 'filled_black',
          size: 'large',
          shape: 'rectangular',
          text: modo === 'register' ? 'signup_with' : 'signin_with',
          logo_alignment: 'center',
          locale: 'pt-BR',
          width: largura,
        })

        /* "Chamei o renderButton" não é o mesmo que "o botão apareceu": com
           client_id errado ou origem não autorizada, o Google não desenha
           nada e não lança erro nenhum. Sem conferir o DOM, a tela mostraria
           um separador "ou" pendurado sobre um vazio. A segunda checagem
           existe porque o widget pode chegar um instante depois. */
        const confirma = () => {
          if (cancelado) return
          const apareceu = (containerRef.current?.childElementCount ?? 0) > 0
          setPronto(apareceu)
          avisaRef.current?.(apareceu)
        }
        confirma()
        setTimeout(confirma, 1200)
      })
      .catch(() => {
        // Silencioso de propósito: o Google fora do ar não é problema de quem
        // ia entrar com senha, e um alerta vermelho aqui só assustaria.
        if (cancelado) return
        avisaRef.current?.(false)
      })

    return () => { cancelado = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modo])

  /* `h-0 overflow-hidden` em vez de `hidden`: o container precisa estar no
     fluxo pra ter LARGURA (é dela que sai o `width` passado pro widget, e um
     `display:none` mediria zero), mas não pode deixar um buraco na tela
     enquanto o Google não responde · ou de vez, se ele nunca responder. */
  return (
    <div
      ref={containerRef}
      className={`w-full flex justify-center ${pronto ? '' : 'h-0 overflow-hidden'}`}
    />
  )
}
