import { createContext, useCallback, useContext, useEffect, useRef, useState, ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'
import api from '../services/api'
import {
  MAX_PASSOS, TOTAL_PASSOS_VIP, TOUR_BOAS_VINDAS, TOUR_VIP, totalDoTour,
  type ContextoTour, type NomeTour,
} from '../components/onboarding/constantes'

/*
 * Estado dos tours guiados.
 *
 * São dois: o de boas-vindas, que abre no primeiro acesso da conta, e o do VIP,
 * que abre quando o acesso completo é liberado e mostra o que a assinatura
 * destravou.
 *
 * A pergunta "esta pessoa já viu este tour?" é da CONTA, não do navegador, então
 * quem responde é o servidor (users.tutorial_status e users.vip_tour_status).
 * Não há espelho em localStorage de propósito: ele faria sair e entrar de novo,
 * trocar de aparelho ou abrir numa aba anônima devolverem o tour para quem já
 * passou por ele, que é justamente o defeito que este desenho evita.
 *
 * O provider é barato para quem está deslogado: sem usuário, nenhuma requisição
 * sai. O overlay só é montado (e só então baixado) quando um tour abre de fato ·
 * ver o OnboardingSlot em App.tsx.
 */

type Status = 'pending' | 'completed' | 'skipped'
interface EstadoDeTour { status: Status; step: number }

interface OnboardingCtx {
  /** Algum tour está na tela agora. */
  aberto: boolean
  /** Qual roteiro está aberto, ou null. */
  tour: NomeTour | null
  /**
   * O tour se recolheu para deixar a página trabalhar.
   *
   * Usado quando um passo abre um formulário de verdade (o da banca abre o
   * SetupModal). O tour continua aberto, só não desenha nada por cima.
   */
  pausado: boolean
  /** Índice do passo atual, 0-based, dentro do roteiro aberto. */
  passo: number
  total: number
  /**
   * Algum tour VAI abrir sozinho, assim que a rota permitir.
   *
   * Note que não é "algum estado está pending". O tour do VIP fica `pending`
   * para toda conta free (é isso que faz ele aparecer no dia da assinatura), e
   * ler isso como "vai abrir" silenciaria para sempre os avisos de rodapé de
   * quem nunca vai assinar. Só conta o que realmente abre agora.
   */
  pendente: boolean
  /**
   * O servidor já respondeu sobre os dois roteiros.
   *
   * Existe porque `pendente` é falso em dois casos diferentes: "já viu" e
   * "ainda não sei". Quem usa `pendente` para decidir se mostra o PRÓPRIO aviso
   * precisa distinguir os dois, ou dispara no primeiro quadro e leva o popup
   * para cima do tour mesmo assim.
   */
  carregado: boolean
  /** O que muda o roteiro de boas-vindas. Congelado enquanto o tour está aberto. */
  contexto: ContextoTour
  abrir: (tour?: NomeTour, de?: number) => void
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
 * Onde um tour pode abrir sozinho. Lista de PERMISSÃO, como em GlobalModals: o
 * provider vive fora do <Routes>, então sem isto o tour apareceria por cima da
 * landing, do blog, dos termos e do link público de pick compartilhado.
 *
 * /checkout fica de fora de propósito · não se interrompe um pagamento em
 * andamento, e é justamente de lá que a pessoa sai recém-VIP. O tour do VIP
 * espera ela chegar em /picks. /admin também fica fora: conta de admin não
 * precisa aprender a plataforma.
 */
const ROTAS_DE_APP = ['/picks', '/banca', '/meus-picks', '/fixtures', '/estatisticas', '/agente', '/profile']

const CONTEXTO_VAZIO: ContextoTour = { emailPendente: false, trialNaMesa: false, semTelefone: false }

/** Teto por roteiro, para o clamp do passo salvo. */
const TETO: Record<NomeTour, number> = {
  'boas-vindas': MAX_PASSOS,
  vip: TOTAL_PASSOS_VIP,
}

export function OnboardingProvider({ children }: { children: ReactNode }) {
  const { user, isAdmin, isVip } = useAuth()
  const { pathname } = useLocation()

  const [estados, setEstados] = useState<Partial<Record<NomeTour, EstadoDeTour>>>({})
  const [tour, setTour] = useState<NomeTour | null>(null)
  const [pausado, setPausado] = useState(false)
  const [passo, setPasso] = useState(0)
  /* Trava desta sessão de página, POR ROTEIRO. O status no servidor é a
     garantia de verdade, mas ele leva um instante para voltar do PUT · sem
     isto o efeito de auto-abrir reabriria o tour no quadro seguinte ao "Pular
     tutorial". Por roteiro, e não global, para que fechar o de boas-vindas não
     tranque o do VIP na mesma sessão. */
  const encerrados = useRef<Set<NomeTour>>(new Set())

  /*
   * O roteiro de boas-vindas depende da conta, e é congelado quando ele abre.
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
    semTelefone: !user?.phone,
  }
  const [contexto, setContexto] = useState<ContextoTour>(CONTEXTO_VAZIO)
  const total = tour ? totalDoTour(tour, contexto) : totalDoTour(TOUR_BOAS_VINDAS, contexto)

  // Lê o estado dos dois roteiros. Duas requisições pequenas por login, em
  // paralelo, e nenhuma para quem está deslogado. Falha em silêncio para
  // 'completed': erro de rede não é motivo para jogar um tour na cara de quem
  // provavelmente já o viu.
  useEffect(() => {
    if (!user) {
      setEstados({})
      setTour(null)
      setPausado(false)
      setPasso(0)
      encerrados.current.clear()
      return
    }
    let vivo = true
    const ler = (nome: NomeTour) =>
      api.get('/personal/tutorial', { params: { tour: nome } })
        .then(r => ({
          nome,
          estado: {
            status: (r.data?.should_start ? 'pending' : 'completed') as Status,
            step: Math.min(Math.max(Number(r.data?.step) || 0, 0), TETO[nome] - 1),
          },
        }))
        .catch(() => ({ nome, estado: { status: 'completed' as Status, step: 0 } }))

    Promise.all([ler(TOUR_BOAS_VINDAS), ler(TOUR_VIP)]).then(res => {
      if (!vivo) return
      setEstados(Object.fromEntries(res.map(r => [r.nome, r.estado])))
    })
    return () => { vivo = false }
  }, [user?.id])

  const carregado = estados[TOUR_BOAS_VINDAS] != null && estados[TOUR_VIP] != null

  /*
   * Qual roteiro deve abrir sozinho agora, se algum.
   *
   * Boas-vindas tem precedência: quem nunca viu o produto precisa entender o
   * fluxo antes de ouvir o que a assinatura abriu. Os dois na mesma sessão
   * seriam treze passos seguidos.
   */
  const proximoAutomatico: NomeTour | null =
    !user || isAdmin || !carregado ? null
    : estados[TOUR_BOAS_VINDAS]?.status === 'pending' && !encerrados.current.has(TOUR_BOAS_VINDAS) ? TOUR_BOAS_VINDAS
    : isVip && estados[TOUR_VIP]?.status === 'pending' && !encerrados.current.has(TOUR_VIP) ? TOUR_VIP
    : null

  /*
   * Baixa o chunk do overlay assim que se sabe que ele vai ser usado.
   *
   * O tour só é MONTADO quando abre (senão todo mundo baixaria os dois roteiros
   * em toda visita), e montar e baixar ao mesmo tempo colocaria uma ida à rede
   * entre o cadastro e a primeira tela. Aqui o download começa antes, em
   * paralelo com a página, e quando o tour abre o módulo já está em memória.
   */
  useEffect(() => {
    if (!proximoAutomatico) return
    import('../components/onboarding/OnboardingTour').catch(() => {})
  }, [proximoAutomatico])

  const salvar = useCallback((nome: NomeTour, corpo: { status?: Status; step?: number }) => {
    // Fire and forget: a tela já reagiu. Se o PUT falhar, o pior que acontece é
    // o tour voltar no próximo login · melhor do que travar o botão "Próximo"
    // esperando a rede.
    api.put('/personal/tutorial', corpo, { params: { tour: nome } }).catch(() => {})
  }, [])

  const abrir = useCallback((nome: NomeTour = TOUR_BOAS_VINDAS, de = 0) => {
    // A Navbar também roda em página pública (Blog, Resultados, pick
    // compartilhado). Sem esta linha, um visitante deslogado abriria o tour e
    // no passo da banca seria jogado na tela de login pelo PrivateRoute.
    if (!user) return
    encerrados.current.delete(nome)
    setContexto(contextoAgora)
    setPasso(Math.max(0, Math.min(de, totalDoTour(nome, contextoAgora) - 1)))
    setPausado(false)
    setTour(nome)
  }, [user, contextoAgora.emailPendente, contextoAgora.trialNaMesa, contextoAgora.semTelefone])

  const encerrar = useCallback((novo: Status) => {
    if (!tour) return
    encerrados.current.add(tour)
    setTour(null)
    setPausado(false)
    setEstados(e => ({ ...e, [tour]: { status: novo, step: e[tour]?.step ?? 0 } }))
    salvar(tour, { status: novo })
  }, [salvar, tour])

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
     para quem ainda está no primeiro contato com aquele roteiro: quem reabriu
     pelo menu já concluiu, e mexer no passo salvo dele não muda nada. */
  useEffect(() => {
    if (!tour) return
    if (estados[tour]?.status !== 'pending') return
    salvar(tour, { step: passo })
  }, [passo, tour])

  // Abertura automática. Só em rota de app, e só depois que o servidor
  // respondeu · abrir antes disso mostraria o tour por meio segundo para quem
  // já o tinha concluído.
  const emRotaDeApp = ROTAS_DE_APP.some(r => pathname === r || pathname.startsWith(`${r}/`))

  useEffect(() => {
    if (!proximoAutomatico || tour || !emRotaDeApp) return
    abrir(proximoAutomatico, estados[proximoAutomatico]?.step ?? 0)
  }, [proximoAutomatico, tour, emRotaDeApp])

  return (
    <Ctx.Provider value={{
      aberto: tour !== null,
      tour,
      pausado,
      passo,
      total,
      pendente: proximoAutomatico !== null,
      carregado,
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
