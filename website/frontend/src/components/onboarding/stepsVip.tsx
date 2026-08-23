import type { LucideIcon } from 'lucide-react'
import {
  BarChart2, Bot, CircleCheck, Crown, Layers, ShieldQuestion, Sparkles, Trophy,
  TrendingUp, Zap,
} from 'lucide-react'
import type { TourStep } from './steps'
import { Etiqueta, Lista, Linhas } from './steps'
import { TOTAL_PASSOS_VIP } from './constantes'

/*
 * O roteiro de boas-vindas ao VIP.
 *
 * Aparece uma vez, no primeiro acesso depois que o acesso completo abre (pago
 * ou trial), e responde a única pergunta de quem acabou de assinar: o que
 * mudou na minha tela?
 *
 * Os alvos são as ABAS REAIS que estavam com cadeado até agora. `data-aba` já
 * existia em Picks.tsx (a barra usa esse atributo para centralizar a aba ativa
 * ao voltar por deep link), então o tour se pendura nele em vez de espalhar um
 * `data-tour` novo por cada aba · um atributo a menos para alguém esquecer de
 * manter quando renomear uma aba.
 *
 * TUDO AQUI TEM QUE SER VERDADE. Cada área citada é gated de fato: as quatro
 * abas por `canSeeVip` em Picks.tsx, as estatísticas de partida por
 * `canSeeStats` em Fixtures.tsx e o Agente por VIP em routers/chat.py.
 * Prometer no tour de boas-vindas uma coisa que a assinatura não abre é a pior
 * hora possível para quebrar confiança.
 *
 * DUAS COISAS FICARAM DE FORA por essa mesma régua, mesmo sendo VIP no papel:
 *
 *   - a aba Picks Ao Vivo é `verAoVivo`, que hoje só é verdadeiro para ADMIN
 *     (o produto ainda não abriu). Citá-la mandaria o assinante procurar uma
 *     aba que ele não tem.
 *   - a página /estatisticas exige VIP, mas não tem link em lugar nenhum do
 *     site. Anunciar uma tela que não se alcança é pior que o silêncio.
 */

const AVISO_ATRASO = (
  <p className="text-[11px] text-ink-4 leading-relaxed">
    Se a aba ainda aparecer vazia, é porque os picks de hoje ainda não saíram.
    Eles não têm horário fixo, e você recebe um aviso quando forem publicados.
  </p>
)

export const TOUR_STEPS_VIP: TourStep[] = [
  {
    id: 'vip-bem-vindo',
    titulo: 'Seu acesso VIP está liberado',
    Icon: Crown,
    resumo: 'A partir de agora todos os picks do dia aparecem abertos para você, com a análise completa da IA.',
    avancar: 'Ver o que abriu',
    corpo: (
      <div className="space-y-3">
        <Etiqueta>O que deixou de ter cadeado</Etiqueta>
        <Lista
          itens={[
            [Zap, 'Picks VIP do dia'],
            [Layers, 'Múltiplas'],
            [TrendingUp, 'Alavancagem'],
            [ShieldQuestion, 'Faltas e defesas'],
            [Trophy, 'Estatísticas de cada jogo'],
            [Bot, 'Agente IA'],
          ]}
        />
        <p className="text-[11px] text-ink-3 leading-relaxed">
          Leva menos de um minuto para ver onde fica cada coisa. Este tour aparece uma
          vez, agora.
        </p>
      </div>
    ),
  },
  {
    id: 'vip-picks',
    titulo: 'Picks VIP do dia',
    Icon: Zap,
    rota: '/picks',
    alvos: ['[data-aba="vip"]', '[data-tour="picks-area"]'],
    resumo: 'Esta aba era a que mostrava cadeado. Agora ela abre os picks do dia inteiros, com mercado, odd, probabilidade e o raciocínio da IA.',
    corpo: (
      <div className="space-y-3">
        <Etiqueta>O que cada card passa a mostrar</Etiqueta>
        <Lista
          itens={[
            [Zap, 'O mercado da entrada'],
            [BarChart2, 'Probabilidade e valor esperado'],
            [Sparkles, 'A análise que sustenta o pick'],
            [TrendingUp, 'Quantas unidades apostar'],
          ]}
        />
        {AVISO_ATRASO}
      </div>
    ),
  },
  {
    id: 'vip-multipla-alavancagem',
    titulo: 'Múltiplas e Alavancagem',
    Icon: Layers,
    rota: '/picks',
    alvos: ['[data-aba="multiplas"]', '[data-aba="alavancagem"]', '[data-tour="picks-area"]'],
    resumo: 'Duas abas novas, com lógicas diferentes de risco.',
    corpo: (
      <div className="space-y-3">
        <Linhas
          itens={[
            ['Múltipla', '2 a 4 seleções num bilhete só'],
            ['Alavancagem', 'Um caminho de até 6 greens seguidos'],
          ]}
        />
        <p className="text-xs text-ink-2 leading-relaxed">
          A alavancagem não é uma aposta por dia, é um caminho: você entra com um valor e
          reaposta o bolo a cada green. Um red custa só a entrada, nunca o acumulado, e o
          que está rodando só entra na sua banca quando o caminho fecha.
        </p>
      </div>
    ),
  },
  {
    id: 'vip-mercados',
    titulo: 'Faltas e defesas de goleiro',
    Icon: ShieldQuestion,
    rota: '/picks',
    alvos: ['[data-aba="mercados"]', '[data-tour="picks-area"]'],
    resumo: 'A aba Mercados traz dois mercados que o motor calcula separado dos gols: total de faltas e defesas do goleiro.',
    corpo: (
      <div className="space-y-3">
        <p className="text-xs text-ink-2 leading-relaxed">
          Eles aparecem com menos frequência que os picks de gols, porque dependem de
          estatística que nem todo jogo tem. Quando aparecem, vêm com a mesma análise
          completa.
        </p>
        {AVISO_ATRASO}
      </div>
    ),
  },
  {
    id: 'vip-jogos',
    titulo: 'Estatísticas de cada jogo',
    Icon: Trophy,
    rota: '/picks',
    alvos: ['[data-tour="nav-jogos"]'],
    resumo: 'Na aba Jogos, clicar numa partida passa a abrir os números dela em vez do convite para assinar.',
    corpo: (
      <div className="space-y-3">
        <p className="text-xs text-ink-2 leading-relaxed">
          São os mesmos números que o motor lê para decidir os picks · escanteios, faltas,
          cartões e chutes, jogo a jogo. Serve tanto para conferir um pick quanto para
          olhar uma partida que a IA não escolheu.
        </p>
        <p className="text-[11px] text-ink-3 leading-relaxed">
          O cadeado que aparecia ao clicar num jogo não aparece mais.
        </p>
      </div>
    ),
  },
  {
    id: 'vip-agente',
    titulo: 'Agente IA',
    Icon: Bot,
    rota: '/picks',
    alvos: ['[data-tour="agente"]', '[data-aba="hoje"]'],
    resumo: 'O assistente passa a responder sobre os picks, os jogos e os números do sistema, e não só as perguntas frequentes.',
    avancar: 'Começar a usar',
    corpo: (
      <div className="space-y-3">
        <Etiqueta>Do que dá para perguntar</Etiqueta>
        <Lista
          itens={[
            [Zap, 'Por que este pick saiu'],
            [BarChart2, 'Como está o desempenho da IA'],
            [TrendingUp, 'O que os números de um jogo dizem'],
            [CircleCheck, 'O que significa um mercado'],
          ]}
        />
        <p className="text-[11px] text-ink-3 leading-relaxed">
          Ele fica neste botão, em qualquer tela.
        </p>
      </div>
    ),
  },
]

/* A conta tem que bater com `constantes.ts`, que é de onde o provider tira o
   total sem importar este arquivo. Divergindo, o "N de M" do balão mente. */
if (import.meta.env.DEV && TOUR_STEPS_VIP.length !== TOTAL_PASSOS_VIP) {
  console.warn(
    `[onboarding] TOTAL_PASSOS_VIP vale ${TOTAL_PASSOS_VIP} mas o roteiro tem ${TOUR_STEPS_VIP.length}.`,
  )
}
