import { createContext, useCallback, useContext, useEffect, useRef, useState, ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'
import api from '../services/api'
import { MAX_PASSOS, totalDePassos, type ContextoTour } from '../components/onboarding/constantes'

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
 * usuário nenhuma requisição sai, e o overlay só é montado (e só então baixado)
 * quando o tour realmente abre. Ver o OnboardingSlot em App.tsx.
 */

type Status = 'pending' | 'completed' | 'skipped'

interface OnboardingCtx {
  /** O overlay está na tela agora. */
  aberto: boolean
  /**
   * O tour se recolheu para deixar a página trabalhar.
   *
   * Usado quando um passo abre um formulário de verdade (o da banca abre o
   * SetupModal). O tour continua aberto, só não desenha nada por cima.
   */
  pausado: boolean
  /** Índice do passo atual, 0-based, dentro do roteiro DESTA conta. */
  passo: number
  total: number
  /** Ainda pode abrir sozinho · outras telas usam para não empilhar aviso. */
  pendente: boolean
  /**
   * O servidor já respondeu.
   *
   * Existe porque `pendente` é falso em dois casos diferentes: "já viu o tour"
   * e "ainda não sei". Quem usa `pendente` para decidir se mostra o PRÓPRIO
   * aviso precisa distinguir os dois, ou dispara no primeiro quadro e leva o
   * popup para cima do tour mesmo assim.
   */
  carregado: boolean
  /** O que muda o roteiro nesta conta. Congelado enquanto o tour está aberto. */
  contexto: ContextoTour
  abrir: (de?: number) => void
  proximo: () => void
  voltar: () => void
  irPara: (i: number) => void
  pular: () => void
  concluir: () => void
  pausar: () => void
  /** Volta a desenhar. `avancar` pula para o passo seguinte, ao concluir a ação. */
  retomar: (avancar?: boolean) => void
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

const CONTEXTO_VAZIO: ContextoTour = { emailPendente: false, trialNaMesa: false }

export function OnboardingProvider({ children }: { children: ReactNode }) {
  const { user, isAdmin } = useAuth()
  const { pathname } = useLocation()

  const [status, setStatus] = useState<Status | null>(null)
  const [aberto, setAberto] = useState(false)
  const [pausado, setPausado] = useState(false)
  const [passo, setPasso] = useState(0)
  /* Trava desta sessão de página. O status no servidor é a garantia de
     verdade, mas ele leva um instante para voltar do PUT · sem isto o efeito
     de auto-abrir reabriria o tour no quadro seguinte ao "Pular tutorial". */
  const encerradoAqui = useRef(false)

  /*
   * O roteiro depende da conta, e é congelado quando o tour abre.
   *
   * O passo do e-mail só existe para quem tem os 2 dias de VIP esperando do
   * outro lado do clique. Se a pessoa confirmar o e-mail numa outra aba no meio
   * do tour, `/auth/me` traria `email_verified: true` no próximo foco da janela
   * e o passo sumiria do MEIO da fila · o "3 de 8" que ela está lendo passaria a
   * apontar para outro passo. Congelado, o roteiro de uma sessão é estável do
   * começo ao fim, e a conferência do e-mail vale a partir da próxima abertura.
   */
  const contextoAgora: ContextoTour = {
    emailPendente: user?.email_verified === false,
    trialNaMesa: user?.trial_used !== true,
  }
  const [contexto, setContexto] = useState<ContextoTour>(CONTEXTO_VAZIO)
  const total = totalDePassos(contexto)

  // Lê o estado da conta. Uma requisição por login, nenhuma para quem está
  // deslogado. Falha em silêncio para 'completed': erro de rede não é motivo
  // para jogar um tour na cara de quem provavelmente já o viu.
  useEffect(() => {
    if (!user) {
      setStatus(null)
      setAberto(false)
      setPausado(false)
      setPasso(0)
      encerradoAqui.current = false
      return
    }
    let vivo = true
    api.get('/personal/tutorial')
      .then(r => {
        if (!vivo) return
        setStatus(r.data?.should_start ? 'pending' : 'completed')
        setPasso(Math.min(Math.max(Number(r.data?.step) || 0, 0), MAX_PASSOS - 1))
      })
      .catch(() => { if (vivo) setStatus('completed') })
    return () => { vivo = false }
  }, [user?.id])

  /*
   * Baixa o chunk do overlay assim que se sabe que ele vai ser usado.
   *
   * O tour só é MONTADO quando abre (senão todo mundo baixaria o roteiro dos
   * sete passos em toda visita), e montar e baixar ao mesmo tempo colocaria uma
   * ida à rede entre o cadastro e a primeira tela. Aqui o download começa antes,
   * em paralelo com a página, e quando o tour abre o módulo já está em memória.
   */
  useEffect(() => {
    if (status !== 'pending') return
    import('../components/onboarding/OnboardingTour').catch(() => {})
  }, [status])

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
    setContexto(contextoAgora)
    setPasso(Math.max(0, Math.min(de, totalDePassos(contextoAgora) - 1)))
    setPausado(false)
    setAberto(true)
  }, [user, contextoAgora.emailPendente, contextoAgora.trialNaMesa])

  const encerrar = useCallback((novo: Status) => {
    encerradoAqui.current = true
    setAberto(false)
    setPausado(false)
    setStatus(novo)
    salvar({ status: novo })
  }, [salvar])

  const pular    = useCallback(() => encerrar('skipped'),   [encerrar])
  const concluir = useCallback(() => encerrar('completed'), [encerrar])

  const irPara = useCallback((i: number) => {
    // Só mexe na posição. Quem GRAVA é o efeito de `passo` lá embaixo, num
    // lugar só: o passo também anda por `retomar(true)`, e com a gravação
    // espalhada pelos dois caminhos um deles ia esquecer de salvar.
    setPasso(Math.max(0, Math.min(i, total - 1)))
  }, [total])

  const proximo = useCallback(() => irPara(passo + 1), [irPara, passo])
  const voltar  = useCallback(() => irPara(passo - 1), [irPara, passo])

  const pausar = useCallback(() => setPausado(true), [])

  const retomar = useCallback((avancar?: boolean) => {
    // A guarda importa: a página da Banca chama `retomar()` ao desmontar, e sem
    // ela uma navegação qualquer avançaria o tour sem ninguém ter configurado
    // banca nenhuma.
    if (!pausado) return
    setPausado(false)
    if (avancar) setPasso(p => Math.min(p + 1, total - 1))
  }, [pausado, total])

  /* Onde a posição é gravada. Um lugar só, olhando o resultado, em vez de uma
     chamada em cada caminho que mexe no passo (`irPara`, `retomar`). Só vale
     para quem ainda está no primeiro contato: quem reabriu pelo menu já
     concluiu, e mexer no passo salvo dele não muda nada. */
  useEffect(() => {
    if (aberto && status === 'pending') salvar({ step: passo })
  }, [passo, aberto, status, salvar])

  // Abertura automática. Só no primeiro acesso da conta, só em rota de app e
  // só depois que o servidor respondeu · abrir antes disso mostraria o tour por
  // meio segundo para quem já o tinha concluído.
  const emRotaDeApp = ROTAS_DE_APP.some(r => pathname === r || pathname.startsWith(`${r}/`))

  useEffect(() => {
    if (!user || isAdmin) return
    if (status !== 'pending' || aberto || encerradoAqui.current) return
    if (!emRotaDeApp) return
    abrir(passo)
  }, [user?.id, isAdmin, status, aberto, emRotaDeApp])

  return (
    <Ctx.Provider value={{
      aberto,
      pausado,
      passo,
      total,
      pendente: status === 'pending',
      carregado: status !== null,
      contexto,
      abrir,
      proximo,
      voltar,
      irPara,
      pular,
      concluir,
      pausar,
      retomar,
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
