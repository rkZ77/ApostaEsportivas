import { createContext, useCallback, useContext, useEffect, useRef, useState, ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'
import api from '../services/api'
import { TOTAL_PASSOS } from '../components/onboarding/constantes'

/*
 * Estado do onboarding interativo.
 *
 * A pergunta "esta pessoa já viu o tour?" é da CONTA, não do navegador, então
 * quem responde é o servidor (users.tutorial_status). Não há espelho em
 * localStorage de propósito: ele faria sair e entrar de novo, trocar de
 * aparelho ou abrir numa aba anônima devolverem o tour para quem já passou por
 * ele, que é justamente o defeito que este desenho evita.
 *
 * O provider é barato para quem está deslogado e para quem já concluiu: sem
 * usuário nenhuma requisição sai, e o overlay é `lazy()` em App.tsx, então quem
 * não vê o tour também não baixa o código dele.
 */

type Status = 'pending' | 'completed' | 'skipped'

interface OnboardingCtx {
  /** O overlay está na tela agora. */
  aberto: boolean
  /** Índice do passo atual, 0-based. */
  passo: number
  total: number
  /** Ainda pode abrir sozinho · outras telas usam para não empilhar popup. */
  pendente: boolean
  /**
   * O servidor já respondeu.
   *
   * Existe porque `pendente` é falso em dois casos diferentes: "já viu o tour"
   * e "ainda não sei". Quem usa `pendente` para decidir se mostra a PRÓPRIA
   * sobreposição (o convite de banca em /picks) precisa distinguir os dois, ou
   * dispara no primeiro quadro e leva o popup para cima do tour mesmo assim.
   */
  carregado: boolean
  abrir: (de?: number) => void
  proximo: () => void
  voltar: () => void
  irPara: (i: number) => void
  pular: () => void
  concluir: () => void
}

const Ctx = createContext<OnboardingCtx | null>(null)

/*
 * Onde o tour pode abrir sozinho. Lista de PERMISSÃO, como em GlobalModals: o
 * provider vive fora do <Routes>, então sem isto o tour apareceria por cima da
 * landing, do blog, dos termos e do link público de pick compartilhado.
 *
 * /checkout fica de fora de propósito · não se interrompe um pagamento em
 * andamento. /admin também: conta de admin não precisa aprender a plataforma.
 */
const ROTAS_DE_APP = ['/picks', '/banca', '/meus-picks', '/fixtures', '/estatisticas', '/agente', '/profile']

export function OnboardingProvider({ children }: { children: ReactNode }) {
  const { user, isAdmin } = useAuth()
  const { pathname } = useLocation()

  const [status, setStatus] = useState<Status | null>(null)
  const [aberto, setAberto] = useState(false)
  const [passo, setPasso] = useState(0)
  /* Trava desta sessão de página. O status no servidor é a garantia de
     verdade, mas ele leva um instante para voltar do PUT · sem isto o efeito
     de auto-abrir reabriria o tour no quadro seguinte ao "Pular tutorial". */
  const encerradoAqui = useRef(false)

  // Lê o estado da conta. Uma requisição por login, nenhuma para quem está
  // deslogado. Falha em silêncio para 'completed': erro de rede não é motivo
  // para jogar um tour na cara de quem provavelmente já o viu.
  useEffect(() => {
    if (!user) {
      setStatus(null)
      setAberto(false)
      setPasso(0)
      encerradoAqui.current = false
      return
    }
    let vivo = true
    api.get('/personal/tutorial')
      .then(r => {
        if (!vivo) return
        setStatus(r.data?.should_start ? 'pending' : 'completed')
        setPasso(Math.min(Math.max(Number(r.data?.step) || 0, 0), TOTAL_PASSOS - 1))
      })
      .catch(() => { if (vivo) setStatus('completed') })
    return () => { vivo = false }
  }, [user?.id])

  const salvar = useCallback((corpo: { status?: Status; step?: number }) => {
    // Fire and forget: a tela já reagiu. Se o PUT falhar, o pior que acontece é
    // o tour voltar no próximo login · melhor do que travar o botão "Próximo"
    // esperando a rede.
    api.put('/personal/tutorial', corpo).catch(() => {})
  }, [])

  const abrir = useCallback((de = 0) => {
    // A Navbar também roda em página pública (Blog, Resultados, pick
    // compartilhado). Sem esta linha, um visitante deslogado abriria o tour e
    // no passo da banca seria jogado na tela de login pelo PrivateRoute.
    if (!user) return
    encerradoAqui.current = false
    setPasso(Math.max(0, Math.min(de, TOTAL_PASSOS - 1)))
    setAberto(true)
  }, [user])

  const encerrar = useCallback((novo: Status) => {
    encerradoAqui.current = true
    setAberto(false)
    setStatus(novo)
    salvar({ status: novo })
  }, [salvar])

  const pular    = useCallback(() => encerrar('skipped'),   [encerrar])
  const concluir = useCallback(() => encerrar('completed'), [encerrar])

  const irPara = useCallback((i: number) => {
    const alvo = Math.max(0, Math.min(i, TOTAL_PASSOS - 1))
    setPasso(alvo)
    // Só guarda a posição de quem ainda está no primeiro contato. Quem reabriu
    // pelo menu já concluiu, e mexer no passo salvo dele não muda nada.
    if (status === 'pending') salvar({ step: alvo })
  }, [salvar, status])

  const proximo = useCallback(() => irPara(passo + 1), [irPara, passo])
  const voltar  = useCallback(() => irPara(passo - 1), [irPara, passo])

  // Abertura automática. Só no primeiro acesso da conta, só em rota de app e
  // só depois que o servidor respondeu · abrir antes disso mostraria o tour por
  // meio segundo para quem já o tinha concluído.
  const emRotaDeApp = ROTAS_DE_APP.some(r => pathname === r || pathname.startsWith(`${r}/`))

  useEffect(() => {
    if (!user || isAdmin) return
    if (status !== 'pending' || aberto || encerradoAqui.current) return
    if (!emRotaDeApp) return
    setAberto(true)
  }, [user?.id, isAdmin, status, aberto, emRotaDeApp])

  return (
    <Ctx.Provider value={{
      aberto,
      passo,
      total: TOTAL_PASSOS,
      pendente: status === 'pending',
      carregado: status !== null,
      abrir,
      proximo,
      voltar,
      irPara,
      pular,
      concluir,
    }}>
      {children}
    </Ctx.Provider>
  )
}

export function useOnboarding() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useOnboarding precisa estar dentro de OnboardingProvider')
  return ctx
}
