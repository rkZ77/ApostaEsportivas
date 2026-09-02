import { useState } from 'react'
import type { LucideIcon } from 'lucide-react'
import {
  ArrowDown, BarChart2, ClipboardCheck, ClipboardList, CircleCheck, ExternalLink,
  Mail, MessageCircle, Radio, Search, ShieldCheck, Sparkles, Ticket, TrendingUp,
  Wallet, Zap,
} from 'lucide-react'
import { useAuth } from '../../context/AuthContext'
import { useOnboarding } from '../../context/OnboardingContext'
import api from '../../services/api'
import { maskPhone } from '../../utils/format'
import {
  EVENTO_CONFIGURAR_BANCA, MAX_PASSOS, passoDoEmailEntra, passoDoWhatsAppEntra,
  totalDePassos,
  type ContextoTour,
} from './constantes'

/*
 * O roteiro do tour.
 *
 * Regra que vale para todos os passos: o destaque aponta para o COMPONENTE
 * REAL da plataforma, nunca para uma reprodução dele. Por isso `alvos` é uma
 * lista de seletores e não um desenho · o passo da banca ilumina o botão
 * Configurar que já existe, o dos picks ilumina o card que já está na tela, o
 * do registro ilumina o botão de apostar. Quando nenhum alvo existe (conta nova
 * num dia sem pick publicado), o passo cai para o modo centrado e continua
 * explicando · o que ele não faz é inventar um card de mentira para iluminar.
 *
 * `alvos` é tentado em ordem e o primeiro seletor que casar no DOM ganha. Os
 * itens seguintes são as áreas maiores que contêm o primeiro, que é o que sobra
 * quando ainda não há pick nenhum.
 *
 * `Lista`, `Linhas` e `Etiqueta` são exportadas porque o roteiro do VIP
 * (stepsVip.tsx) monta os passos dele com as mesmas peças · dois vocabulários
 * visuais para a mesma caixa seria a forma mais rápida de os dois tours
 * pararem de parecer o mesmo produto.
 *
 * Dois passos fazem mais do que explicar: o do e-mail reenvia o link de
 * confirmação e o da banca abre o formulário de verdade. Tour que só aponta
 * deixa a pessoa com a lista de tarefas na cabeça para depois; estes dois
 * resolvem na hora, que é quando ela está com a atenção aqui.
 */

export interface TourStep {
  id: string
  titulo: string
  Icon: LucideIcon
  /** Rota que precisa estar na tela para o alvo existir. Ausente = fica onde está. */
  rota?: string
  /** Candidatos de destaque, em ordem de preferência. */
  alvos?: string[]
  /** Primeira frase do passo. Vive fora do corpo porque é o que o leitor de tela anuncia. */
  resumo: string
  corpo?: React.ReactNode
  /** Rótulo do botão que avança. O padrão é "Próximo". */
  avancar?: string
  /** Passo que não vale para toda conta. Ausente = todo mundo vê. */
  mostrar?: (ctx: ContextoTour) => boolean
}

/* ── Peças de conteúdo ──────────────────────────────────────────────────── */

export function Lista({ itens }: { itens: [LucideIcon, string][] }) {
  return (
    <ul className="grid gap-2 sm:grid-cols-2">
      {itens.map(([Icone, texto]) => (
        <li key={texto} className="flex items-center gap-2 text-xs text-ink-2">
          <Icone className="w-3.5 h-3.5 shrink-0 text-accent-ink" aria-hidden="true" />
          {texto}
        </li>
      ))}
    </ul>
  )
}

/** Linha rótulo/valor. Usada nos exemplos numéricos e na lista de campos. */
export function Linhas({ itens }: { itens: [string, string][] }) {
  return (
    <dl className="rounded-md border border-line bg-surface-2/60 divide-y divide-line">
      {itens.map(([rotulo, valor]) => (
        <div key={rotulo} className="flex items-center justify-between gap-3 px-3 py-2">
          <dt className="text-[11px] text-ink-3">{rotulo}</dt>
          <dd className="text-xs font-mono font-bold text-ink-1 text-right">{valor}</dd>
        </div>
      ))}
    </dl>
  )
}

/**
 * Fluxo vertical com seta entre as etapas.
 *
 * Vertical em qualquer largura de propósito: em duas colunas a seta passa a
 * apontar para os lados na metade do caminho, e a ordem deixa de ser óbvia
 * justamente no passo cuja única mensagem é a ordem das coisas.
 */
function Fluxo({ etapas, destacar }: { etapas: [LucideIcon, string][]; destacar?: number[] }) {
  return (
    <ol className="space-y-0">
      {etapas.map(([Icone, texto], i) => {
        const forte = destacar?.includes(i)
        return (
          <li key={texto}>
            <div
              className={`flex items-center gap-2.5 rounded-md border px-3 py-2 ${
                forte ? 'border-accent/40 bg-accent/10' : 'border-line bg-surface-2/60'
              }`}
            >
              <Icone
                className={`w-4 h-4 shrink-0 ${forte ? 'text-accent-ink' : 'text-ink-3'}`}
                aria-hidden="true"
              />
              <span className={`text-xs ${forte ? 'text-ink-1 font-semibold' : 'text-ink-2'}`}>
                {texto}
              </span>
            </div>
            {i < etapas.length - 1 && (
              <ArrowDown className="w-3.5 h-3.5 text-ink-4 mx-auto my-1" aria-hidden="true" />
            )}
          </li>
        )
      })}
    </ol>
  )
}

/** Caixa de recado firme. É onde mora o que a PickIA NÃO faz. */
function Recado({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex gap-2.5 rounded-md border border-yellow-500/30 bg-yellow-500/10 px-3 py-2.5">
      <ShieldCheck className="w-4 h-4 text-yellow-400 shrink-0 mt-px" aria-hidden="true" />
      <p className="text-[11px] leading-relaxed text-yellow-100">{children}</p>
    </div>
  )
}

export function Etiqueta({ children }: { children: React.ReactNode }) {
  return <p className="text-[10px] font-bold uppercase tracking-wide text-ink-4">{children}</p>
}

/** Ação de verdade dentro do balão. Verde cheio, para se separar do "Próximo". */
function AcaoDoPasso({
  children, onClick, disabled, feito,
}: {
  children: React.ReactNode
  onClick: () => void
  disabled?: boolean
  feito?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || feito}
      className={`w-full inline-flex items-center justify-center gap-2 text-xs font-bold px-3 py-2.5 rounded-md border transition-colors min-h-[40px] ${
        feito
          ? 'border-accent/30 bg-accent/10 text-accent-ink cursor-default'
          : 'border-accent/40 bg-accent/15 text-accent-ink hover:bg-accent/25 disabled:opacity-50'
      }`}
    >
      {children}
    </button>
  )
}

/* ── Passos que fazem alguma coisa ──────────────────────────────────────── */

/**
 * Confirmar o e-mail é o que paga os 2 dias de VIP.
 *
 * O aviso de rodapé que dizia isso (VerifyEmailBanner) fica escondido enquanto
 * o tour está aberto, senão ele pula na frente do tutorial · ele é `z-[9990]`.
 * Então a mensagem tem que estar AQUI, e com o mesmo botão de reenviar, ou a
 * troca esconderia o convite do trial sem repor.
 */
function PassoConfirmarEmail() {
  const { user } = useAuth()
  const [enviando, setEnviando] = useState(false)
  const [enviado, setEnviado] = useState(false)
  const [erro, setErro] = useState(false)

  const reenviar = async () => {
    setEnviando(true)
    setErro(false)
    try {
      await api.post('/auth/resend-verification')
      setEnviado(true)
    } catch {
      setErro(true)
    } finally {
      setEnviando(false)
    }
  }

  return (
    <div className="space-y-3">
      <Etiqueta>O que você ganha</Etiqueta>
      <Linhas itens={[['Teste do VIP', '2 dias'], ['Custo', 'R$ 0,00']]} />
      <p className="text-xs text-ink-2 leading-relaxed">
        O VIP abre todos os picks do dia, as múltiplas e a alavancagem. Sem confirmar,
        a conta segue no plano gratuito, com 1 pick por dia.
      </p>
      {user?.email && (
        <p className="text-[11px] text-ink-3 leading-relaxed">
          Enviamos o link para <span className="text-ink-1 font-semibold break-all">{user.email}</span>.
          Confira também o spam.
        </p>
      )}
      <AcaoDoPasso onClick={reenviar} disabled={enviando} feito={enviado}>
        {enviado
          ? <><CircleCheck className="w-3.5 h-3.5" aria-hidden="true" /> E-mail reenviado</>
          : <><Mail className="w-3.5 h-3.5" aria-hidden="true" /> {enviando ? 'Enviando...' : 'Reenviar o e-mail'}</>}
      </AcaoDoPasso>
      {erro && (
        <p className="text-[11px] text-red-400">
          Não deu para reenviar agora. O link original continua valendo.
        </p>
      )}
      <p className="text-[11px] text-ink-4 leading-relaxed">
        Pode confirmar depois e seguir o tutorial. O VIP entra sozinho assim que você
        clicar no link.
      </p>
    </div>
  )
}

/**
 * Configurar a banca sem sair do tour.
 *
 * O botão pede à página da Banca que abra o `SetupModal` DE VERDADE (o mesmo do
 * botão Configurar) e recolhe o tour enquanto o formulário está na tela. Salvou,
 * o tour volta já no passo seguinte. A alternativa seria desenhar um
 * mini-formulário aqui dentro, e aí existiriam dois lugares para configurar
 * banca com duas validações para divergir.
 */
function PassoBanca() {
  const { pausar } = useOnboarding()

  return (
    <div className="space-y-3">
      <Etiqueta>Exemplo</Etiqueta>
      <Linhas itens={[['Banca inicial', 'R$ 1.000,00'], ['Valor de 1 unidade', 'R$ 10,00']]} />
      <p className="text-xs text-ink-2 leading-relaxed">
        A banca serve como referência para acompanhar lucro, prejuízo, ROI e a evolução
        dos seus resultados. A unidade é quanto você aposta por vez.
      </p>
      <AcaoDoPasso
        onClick={() => {
          pausar()
          window.dispatchEvent(new CustomEvent(EVENTO_CONFIGURAR_BANCA))
        }}
      >
        <Wallet className="w-3.5 h-3.5" aria-hidden="true" />
        Configurar minha banca agora
      </AcaoDoPasso>
      <Recado>
        A banca cadastrada aqui não representa dinheiro depositado na plataforma. A
        PickIA não recebe, não guarda e não movimenta o seu dinheiro. O valor é apenas
        o número de referência do seu acompanhamento.
      </Recado>
    </div>
  )
}

/* ── O roteiro ──────────────────────────────────────────────────────────── */

export /**
 * O telefone, preenchido SEM SAIR DO TOUR.
 *
 * Aqui o campo mora no próprio balão, e não num modal da página de perfil como
 * a banca. A diferença não é estilo: a banca tem três campos, regras de
 * unidade e um aviso legal, então vale abrir o formulário de verdade em vez de
 * manter duas cópias dele. Telefone é UM campo. Mandar a pessoa para outra
 * tela, achar o campo, salvar e voltar, por um campo, é onde ela desiste.
 *
 * Salva no mesmo endpoint do perfil (`PUT /auth/profile`), então a validação
 * de DDD e de nono dígito é a mesma do resto do site · não nasce uma segunda
 * regra de telefone aqui.
 */
function PassoWhatsApp() {
  const { user, refreshUser } = useAuth()
  const [numero, setNumero] = useState('')
  const [salvando, setSalvando] = useState(false)
  const [salvo, setSalvo] = useState(false)
  const [erro, setErro] = useState('')

  const digitos = numero.replace(/\D/g, '')
  const valido = digitos.length >= 10 && digitos.length <= 11

  const salvar = async () => {
    if (!valido) return
    setSalvando(true)
    setErro('')
    try {
      await api.put('/auth/profile', { phone: numero })
      await refreshUser()
      setSalvo(true)
    } catch (e: any) {
      const detalhe = e?.response?.data?.detail
      setErro(typeof detalhe === 'string' ? detalhe : 'Não deu para salvar agora. Tente de novo.')
    } finally {
      setSalvando(false)
    }
  }

  /* Quem já tem número não deveria chegar aqui (o passo é condicional), mas o
     contexto do tour é congelado na abertura: salvar noutra aba no meio do
     caminho deixaria esta tela pedindo o que já existe. */
  const jaTem = salvo || !!user?.phone

  return (
    <div className="space-y-3">
      <Etiqueta>Para que serve o número</Etiqueta>
      <Lista
        itens={[
          [Zap, 'Aviso quando os picks do dia são publicados'],
          [Radio, 'Aviso de pick ao vivo, que é o que tem prazo: a odd dura minutos'],
          [ShieldCheck, 'E é ele que garante uma conta por pessoa'],
        ]}
      />

      {jaTem ? (
        <p className="text-xs text-accent-ink font-semibold flex items-center gap-1.5">
          <CircleCheck className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
          Número salvo. Os avisos já valem para esta conta.
        </p>
      ) : (
        <>
          {/* `type="tel"` e `inputMode="numeric"` abrem o teclado numérico no
              celular, que é de onde vem a maior parte do cadastro. */}
          <label className="block">
            <span className="sr-only">Seu WhatsApp</span>
            <input
              className="input w-full"
              value={numero}
              onChange={e => { setNumero(maskPhone(e.target.value)); setErro('') }}
              onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); salvar() } }}
              placeholder="(11) 99999-9999"
              type="tel"
              inputMode="numeric"
              autoComplete="tel-national"
              maxLength={15}
              aria-invalid={!!erro}
            />
          </label>

          <AcaoDoPasso onClick={salvar} disabled={!valido || salvando}>
            <MessageCircle className="w-3.5 h-3.5" aria-hidden="true" />
            {salvando ? 'Salvando...' : 'Salvar e receber os avisos'}
          </AcaoDoPasso>

          {erro && <p className="text-[11px] text-red-400 leading-relaxed">{erro}</p>}
        </>
      )}

      <p className="text-[11px] text-ink-4 leading-relaxed">
        Pode preencher depois no seu perfil, e desativar os avisos quando quiser.
      </p>
    </div>
  )
}

const TOUR_STEPS: TourStep[] = [
  {
    id: 'bem-vindo',
    titulo: 'Bem-vindo à PickIA',
    Icon: Sparkles,
    resumo: 'Vamos mostrar rapidamente como a PickIA funciona e como você pode começar a acompanhar seus picks de forma organizada.',
    avancar: 'Começar',
    corpo: (
      <div className="space-y-3">
        <Etiqueta>O que você faz por aqui</Etiqueta>
        <Lista
          itens={[
            [Zap, 'Receber picks'],
            [ClipboardList, 'Registrar apostas'],
            [Wallet, 'Controlar a banca'],
            [CircleCheck, 'Acompanhar resultados'],
            [BarChart2, 'Visualizar desempenho'],
            [TrendingUp, 'Acompanhar a evolução da banca'],
          ]}
        />
        <p className="text-[11px] text-ink-3 leading-relaxed">
          São poucos passos e dá para sair a qualquer momento. Para rever depois, o
          menu da sua conta tem Ver tutorial.
        </p>
      </div>
    ),
  },
  {
    id: 'confirmar-email',
    titulo: 'Confirme seu e-mail e ganhe 2 dias de VIP',
    Icon: Mail,
    mostrar: passoDoEmailEntra,
    resumo: 'A conta já está criada. Falta confirmar o e-mail, e é isso que libera os 2 dias de teste do VIP, sem custo nenhum.',
    corpo: <PassoConfirmarEmail />,
  },
  {
    id: 'banca',
    titulo: 'Configure sua banca',
    Icon: Wallet,
    rota: '/banca',
    alvos: ['[data-tour="banca-configurar"]', '[data-tour="banca-resumo"]'],
    resumo: 'Informe o valor que você possui disponível para suas apostas. A PickIA utiliza essa informação para acompanhar sua evolução e calcular seus resultados.',
    corpo: <PassoBanca />,
  },
  {
    id: 'picks',
    titulo: 'Encontre seus picks',
    Icon: Zap,
    rota: '/picks',
    alvos: ['[data-tour="pick-card"]', '[data-tour="picks-area"]'],
    resumo: 'Os picks disponíveis aparecem nesta área com as informações necessárias para você analisar cada oportunidade.',
    corpo: (
      <div className="space-y-3">
        <Etiqueta>O que cada card mostra</Etiqueta>
        <Lista
          itens={[
            [Ticket, 'O jogo e a competição'],
            [Search, 'O mercado da entrada'],
            [TrendingUp, 'A odd sugerida'],
            [BarChart2, 'A análise da IA'],
          ]}
        />
        <p className="text-xs text-ink-2 leading-relaxed">
          Confira as informações do pick antes de realizar sua aposta.
        </p>
      </div>
    ),
  },
  {
    /* O TELEFONE, PEDIDO NA HORA CERTA.
       Ele nunca foi opcional na prática: é o contato do aviso de pick
       publicado e de pick ao vivo, e o ao vivo é o que mais depende disso ·
       a odd dura minutos, então "abrir o site mais tarde" não recupera a
       oportunidade. O cadastro por formulário pede o número; o do Google não,
       e essas contas chegavam sem.

       Fica no fim, e não no cadastro: pedir telefone antes de a pessoa ver o
       produto é onde o cadastro morre, e foi por isso que o CPF saiu em 18/08.
       Aqui ela já viu os picks e já sabe o que perde sem o aviso.

       Só aparece para quem não tem número (ver `passoDoWhatsAppEntra`). */
    id: 'whatsapp',
    titulo: 'Receba os picks no WhatsApp',
    Icon: MessageCircle,
    mostrar: passoDoWhatsAppEntra,
    /* SEM `rota` e SEM `alvos`: o campo está aqui dentro, então não há para
       onde levar nem o que destacar. O balão fica centralizado, igual ao passo
       de confirmar o e-mail · e no celular isso importa, porque navegar para o
       perfil no meio do tour tira a pessoa da tela dos picks. */
    resumo: 'Sua conta ainda está sem telefone. É por ele que avisamos quando um pick sai.',
    corpo: <PassoWhatsApp />,
  },
  {
    id: 'casa-de-apostas',
    titulo: 'A aposta é realizada por você',
    Icon: ExternalLink,
    resumo: 'A PickIA fornece o pick e permite que você registre e acompanhe sua aposta. A aposta é realizada diretamente por você na casa de apostas de sua preferência.',
    corpo: (
      <div className="space-y-3">
        <Fluxo
          destacar={[2, 3]}
          etapas={[
            [Zap, 'Pick recebido'],
            [Search, 'Você analisa'],
            [ExternalLink, 'Você acessa sua casa de apostas'],
            [Ticket, 'Você realiza a aposta'],
            [ClipboardCheck, 'Você registra o pick na PickIA'],
          ]}
        />
        <Recado>
          A PickIA não realiza apostas automaticamente, não movimenta o seu dinheiro e
          não acessa a sua conta nas casas de apostas.
        </Recado>
      </div>
    ),
  },
  {
    id: 'registrar',
    titulo: 'Registre sua aposta',
    Icon: ClipboardCheck,
    rota: '/picks',
    alvos: ['[data-tour="pick-apostar"]', '[data-tour="pick-card"]', '[data-tour="picks-area"]'],
    resumo: 'Depois de realizar a aposta na casa de apostas, volte para a PickIA e registre o pick para acompanhar seu resultado.',
    corpo: (
      <div className="space-y-3">
        <Etiqueta>Campos do registro</Etiqueta>
        {/* Os campos são os que o formulário real pede (ver ApostaModal). A
            stake é em UNIDADES e não em reais: o valor em R$ sai da unidade que
            você definiu na banca, e escrever um campo "Valor apostado" aqui
            prometeria uma caixa que não existe naquela tela. */}
        <Linhas
          itens={[
            ['Casa de aposta', 'Superbet, Bet365, Betano, Outra'],
            ['Odd apostada', '2.05'],
            ['Unidades a apostar', '2u'],
          ]}
        />
        <p className="text-[11px] text-ink-3 leading-relaxed">
          A odd já vem preenchida com a do pick e você ajusta se apostou em outra. As
          unidades viram reais pelo valor de unidade da sua banca, e a IA sugere quantas
          usar.
        </p>
      </div>
    ),
  },
  {
    id: 'resultados',
    titulo: 'Acompanhe sua evolução',
    Icon: TrendingUp,
    rota: '/banca',
    alvos: ['[data-tour="banca-resumo"]', '[data-tour="banca-evolucao"]'],
    resumo: 'Depois de registrar seus picks, acompanhe seus resultados e veja como sua banca está evoluindo.',
    corpo: (
      <div className="space-y-3">
        <Etiqueta>O que esta tela mostra</Etiqueta>
        {/* Só o que existe de verdade na página da Banca. Métrica listada aqui
            e ausente lá vira promessa quebrada no primeiro clique. */}
        <Lista
          itens={[
            [Wallet, 'Banca atual e lucro'],
            [BarChart2, 'Yield e ROI'],
            [CircleCheck, 'Win rate, greens e reds'],
            [TrendingUp, 'Evolução da banca'],
            [ClipboardList, 'Distribuição dos resultados'],
            [Zap, 'Sequência atual e melhor sequência'],
          ]}
        />
        <Etiqueta>Exemplo</Etiqueta>
        <Linhas
          itens={[
            ['Banca inicial', 'R$ 1.000,00'],
            ['Resultado', '+R$ 180,00'],
            ['Banca atual', 'R$ 1.180,00'],
          ]}
        />
      </div>
    ),
  },
  {
    id: 'pronto',
    titulo: 'Tudo pronto',
    Icon: CircleCheck,
    resumo: 'Agora você já sabe como a PickIA funciona.',
    avancar: 'Começar a usar a PickIA',
    corpo: (
      <div className="space-y-3">
        <Etiqueta>O caminho completo</Etiqueta>
        <Fluxo
          etapas={[
            [Wallet, '1. Configure sua banca'],
            [Zap, '2. Receba os picks'],
            [ExternalLink, '3. Realize a aposta na sua casa de apostas'],
            [ClipboardCheck, '4. Registre a aposta na PickIA'],
            [TrendingUp, '5. Acompanhe seus resultados'],
          ]}
        />
        <p className="text-[11px] text-ink-3 leading-relaxed">
          Precisando rever, é só abrir Ver tutorial no menu da sua conta.
        </p>
      </div>
    ),
  },
]

/** O roteiro desta conta. `ctx` vem congelado do provider. */
export function passosDoTour(ctx: ContextoTour): TourStep[] {
  return TOUR_STEPS.filter(p => !p.mostrar || p.mostrar(ctx))
}

/* Os dois arquivos contam os mesmos passos: `constantes.ts` existe para o
   provider saber o total sem importar este aqui (ver o comentário lá). Se a
   conta divergir, o "N de M" do balão mente. Roda uma vez, no import, e some do
   build de produção junto com o `if`. */
if (import.meta.env.DEV) {
  const cheio: ContextoTour = { emailPendente: true, trialNaMesa: true, semTelefone: true }
  const enxuto: ContextoTour = { emailPendente: false, trialNaMesa: false, semTelefone: false }
  if (
    passosDoTour(cheio).length !== totalDePassos(cheio) ||
    passosDoTour(enxuto).length !== totalDePassos(enxuto) ||
    TOUR_STEPS.length !== MAX_PASSOS
  ) {
    console.warn('[onboarding] o roteiro e as constantes discordam do total de passos.')
  }
}
