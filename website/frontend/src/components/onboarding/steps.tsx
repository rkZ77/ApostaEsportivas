import type { LucideIcon } from 'lucide-react'
import {
  ArrowDown, BarChart2, ClipboardCheck, ClipboardList, CircleCheck, ExternalLink,
  Search, ShieldCheck, Sparkles, Ticket, TrendingUp, Undo2, Wallet, Zap,
} from 'lucide-react'
import { TOTAL_PASSOS } from './constantes'

/*
 * O roteiro do tour.
 *
 * Regra que vale para os sete passos: o destaque aponta para o COMPONENTE REAL
 * da plataforma, nunca para uma reprodução dele. Por isso `alvos` é uma lista
 * de seletores e não um desenho · o passo da banca ilumina o botão Configurar
 * que já existe, o dos picks ilumina o card que já está na tela, o do registro
 * ilumina o botão de apostar do card. Quando nenhum alvo existe (conta nova num
 * dia sem pick publicado, por exemplo), o passo cai para o modo centrado e
 * continua explicando · o que ele não faz é inventar um card de mentira só para
 * ter o que iluminar.
 *
 * `alvos` é tentado em ordem e o primeiro seletor que casar no DOM ganha. Os
 * itens seguintes de cada lista são as áreas maiores que contêm o primeiro, que
 * é o que sobra quando ainda não há pick nenhum.
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
}

/* ── Peças de conteúdo ──────────────────────────────────────────────────── */

function Lista({ itens }: { itens: [LucideIcon, string][] }) {
  return (
    <ul className="grid gap-2 sm:grid-cols-2">
      {itens.map(([Icone, texto]) => (
        <li key={texto} className="flex items-center gap-2 text-xs text-ink-2">
          <Icone className="w-3.5 h-3.5 shrink-0 text-accent" aria-hidden="true" />
          {texto}
        </li>
      ))}
    </ul>
  )
}

/** Linha rótulo/valor. Usada nos exemplos numéricos e na lista de campos. */
function Linhas({ itens }: { itens: [string, string][] }) {
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
                className={`w-4 h-4 shrink-0 ${forte ? 'text-accent' : 'text-ink-3'}`}
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

function Etiqueta({ children }: { children: React.ReactNode }) {
  return <p className="text-[10px] font-bold uppercase tracking-wide text-ink-4">{children}</p>
}

/* ── Os sete passos ─────────────────────────────────────────────────────── */

export const TOUR_STEPS: TourStep[] = [
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
          São sete passos rápidos. Você pode sair a qualquer momento e reabrir depois
          pelo menu da sua conta, em Ver tutorial.
        </p>
      </div>
    ),
  },
  {
    id: 'banca',
    titulo: 'Configure sua banca',
    Icon: Wallet,
    rota: '/banca',
    alvos: ['[data-tour="banca-configurar"]', '[data-tour="banca-resumo"]'],
    resumo: 'Informe o valor que você possui disponível para suas apostas. A PickIA utiliza essa informação para acompanhar sua evolução e calcular seus resultados.',
    corpo: (
      <div className="space-y-3">
        <Etiqueta>Exemplo</Etiqueta>
        <Linhas itens={[['Banca inicial', 'R$ 1.000,00']]} />
        <p className="text-xs text-ink-2 leading-relaxed">
          A banca serve como referência para acompanhar lucro, prejuízo, ROI e a evolução
          dos seus resultados.
        </p>
        <Recado>
          A banca cadastrada aqui não representa dinheiro depositado na plataforma. A
          PickIA não recebe, não guarda e não movimenta o seu dinheiro. O valor é apenas
          o número de referência do seu acompanhamento.
        </Recado>
      </div>
    ),
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
            [Undo2, 'Você volta para a PickIA'],
            [ClipboardCheck, 'Você registra o pick'],
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
        <p className="text-xs text-ink-2 leading-relaxed">
          Esse registro permite que a PickIA acompanhe o desempenho da sua aposta e
          atualize seus resultados.
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

/* `constantes.ts` existe para o provider saber o total sem importar este
   arquivo (ver o comentário lá). Os dois números têm que continuar iguais, e
   `TOUR_STEPS.length` é `number` para o TypeScript, então a conferência só pode
   ser em tempo de execução. Roda uma vez, no import, e some do build de
   produção junto com o `if`. */
if (import.meta.env.DEV && TOUR_STEPS.length !== TOTAL_PASSOS) {
  console.warn(
    `[onboarding] TOTAL_PASSOS vale ${TOTAL_PASSOS} mas o roteiro tem ${TOUR_STEPS.length} passos.`,
  )
}
