import type { LucideIcon } from 'lucide-react'
import {
  BarChart2, Bot, CircleCheck, ClipboardCheck, Crown, Layers, Radio, Rocket, ShieldQuestion,
  Sparkles, Trophy, TrendingUp, Wallet, Zap,
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
 * UMA COISA FICOU DE FORA por essa mesma régua, mesmo sendo VIP no papel: a
 * página /estatisticas exige VIP, mas não tem link em lugar nenhum do site.
 * Anunciar uma tela que não se alcança é pior que o silêncio.
 *
 * (Os Picks Ao Vivo também ficavam de fora enquanto `verAoVivo` só valia para
 * ADMIN. O produto abriu em 01/09 e o passo entrou.)
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
            [ShieldQuestion, 'Faltas e picks de jogador'],
            [Rocket, 'Pick Boost'],
            [Radio, 'Picks Ao Vivo'],
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
    /* Este passo apontava pra `[data-aba="mercados"]`, e a aba Mercados deixou
       de existir em 27/08 · o destaque caía no fallback (`picks-area`) e o
       texto descrevia uma tela que ninguém mais ia encontrar.
       Faltas virou seção da aba VIP e Jogadores ganhou aba própria. */
    id: 'vip-jogadores',
    titulo: 'Picks de jogador',
    Icon: ShieldQuestion,
    rota: '/picks',
    alvos: ['[data-aba="jogadores"]', '[data-tour="picks-area"]'],
    resumo: 'Uma aba só para estatística individual: chutes, chutes no alvo, gols, defesas, faltas, desarmes e passes de um jogador específico.',
    corpo: (
      <div className="space-y-3">
        <p className="text-xs text-ink-2 leading-relaxed">
          A média sai das atuações dele na mesma competição, contando só jogo em que ele foi
          titular efetivo, entrada de doze minutos e jogo inteiro não são a mesma coisa.
        </p>
        <p className="text-[11px] text-ink-3 leading-relaxed">
          Faltas continua existindo e agora fica dentro da própria aba VIP, logo abaixo da
          grade de picks.
        </p>
        {AVISO_ATRASO}
      </div>
    ),
  },
  {
    id: 'vip-boost',
    titulo: 'Pick Boost',
    Icon: Rocket,
    rota: '/picks',
    alvos: ['[data-aba="boost"]', '[data-tour="picks-area"]'],
    resumo: 'Uma combinação fixa no mesmo jogo: mais de 1.5 gols no jogo inteiro e menos de 2.5 no primeiro tempo.',
    corpo: (
      <div className="space-y-3">
        <p className="text-xs text-ink-2 leading-relaxed">
          Nos outros produtos o motor olha um jogo e escolhe o melhor mercado dele. Aqui é o
          contrário: o mercado já está definido e o que se escolhe são os jogos, por isso o
          dia costuma ter mais de um.
        </p>
        <p className="text-[11px] text-ink-3 leading-relaxed">
          Um deles é gratuito todo dia, mesmo para quem não é assinante. O resto é seu.
        </p>
      </div>
    ),
  },
  {
    id: 'vip-ao-vivo',
    titulo: 'Picks Ao Vivo',
    Icon: Radio,
    rota: '/picks',
    alvos: ['[data-aba="ao_vivo"]', '[data-tour="picks-area"]'],
    resumo: 'Oportunidades que o motor encontra com o jogo rolando, lendo placar, ritmo e pressão em tempo real.',
    corpo: (
      <div className="space-y-3">
        <p className="text-xs text-ink-2 leading-relaxed">
          A odd ao vivo vale minutos, então o card mostra uma contagem regressiva, o preço
          é o do instante da análise, e vale conferir na casa antes de apostar.
        </p>
        <p className="text-[11px] text-ink-3 leading-relaxed">
          Você recebe um aviso quando o motor publica um pick novo. Quando não há nada, a
          aba diz se o motor está ligado ou parado, são coisas diferentes.
        </p>
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
          São os mesmos números que o motor lê para decidir os picks, escanteios, faltas,
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
{
    /* REGISTRAR E ACOMPANHAR, OUTRA VEZ.
       Os dois passos existem no tour de boas-vindas (steps::registrar e
       steps::resultados) e a repeticao e' deliberada (decisao do usuario,
       02/09). Dois motivos: o tour de boas-vindas pode ter sido pulado, e sem
       registrar a aposta nada do que os passos acima abriram vira resultado na
       banca -- o assinante veria seis abas novas e uma banca parada.

       Nao e' o mesmo texto. La' o assunto e' COMO se registra, campo a campo;
       aqui e' que o botao vale tambem pras abas que acabaram de abrir. */
    id: 'vip-registrar',
    titulo: 'Registre a aposta',
    Icon: ClipboardCheck,
    rota: '/picks',
    alvos: ['[data-tour="pick-apostar"]', '[data-tour="pick-card"]', '[data-tour="picks-area"]'],
    resumo: 'Todo pick tem o botão de registrar, inclusive os das abas que abriram agora.',
    corpo: (
      <div className="space-y-3">
        <p className="text-xs text-ink-2 leading-relaxed">
          A aposta você faz na casa. Aqui você registra o que apostou, e é isso que
          transforma o pick em resultado na sua banca.
        </p>
        <Etiqueta>O que o registro pede</Etiqueta>
        <Linhas
          itens={[
            ['Casa de aposta', 'Superbet, Bet365, Betano, Outra'],
            ['Odd apostada', '2.05'],
            ['Unidades a apostar', '2u'],
          ]}
        />
        <p className="text-[11px] text-ink-3 leading-relaxed">
          A odd vem preenchida com a do pick e você ajusta se apostou em outra. As
          unidades viram reais pelo valor de unidade da sua banca.
        </p>
      </div>
    ),
  },
  {
    id: 'vip-acompanhar',
    titulo: 'Acompanhe sua evolução',
    Icon: TrendingUp,
    rota: '/banca',
    alvos: ['[data-tour="banca-resumo"]', '[data-tour="banca-evolucao"]'],
    resumo: 'A Minha Banca junta tudo que você registrou e mostra se o mês está indo bem.',
    avancar: 'Começar a usar',
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
            [Zap, 'Sequência atual e melhor sequência'],
          ]}
        />
        <p className="text-[11px] text-ink-3 leading-relaxed">
          Os picks de todas as abas caem aqui juntos, então dá para ver qual produto
          está rendendo mais na SUA banca, e não só no placar público.
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
