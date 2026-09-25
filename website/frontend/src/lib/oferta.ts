import {
  Crown, Gift, Layers, Rocket, Wallet, BarChart3, Bot, CalendarDays,
  ShieldHalf, Flag, Radio, Zap, UserSquare, Grid3x3,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { BadgeTone } from '../components/ui'

/*
 * O CATÁLOGO DO QUE A PLATAFORMA ENTREGA · fonte única.
 *
 * Esta lista existia duas vezes, escrita à mão nos dois lugares, e as duas
 * discordavam: a vitrine da Home tinha dez módulos com nome e descrição, e o
 * Checkout tinha seis frases genéricas ("Análise de probabilidades", "Suporte
 * ao Agente de IA") que não citavam múltipla, alavancagem, faltas, defesas,
 * ao vivo, Pick Boost nem Player Stats.
 *
 * Ou seja: a tela em que a pessoa está com o dedo no botão de pagar era a que
 * menos contava o que ela ia levar. Quem vende o produto tem que ler do mesmo
 * lugar que quem o descreve.
 *
 * O `plano` é o que separa as três colunas da página de planos, não é enfeite.
 * Mudar um item aqui muda a Home, a página de planos e o checkout de uma vez,
 * que é exatamente o ponto.
 */

/*
 * QUAL PLANO ABRE O MODULO (12/09/2026, dois planos).
 *
 *   'ambos' · aberto pra qualquer conta, inclusive free
 *   'pago'  · entra nos dois planos pagos (Pick IA e Pick IA Pro)
 *   'pro'   · exclusivo do Pick IA Pro
 *
 * So' dois modulos sao 'pro', e nao foi escolha estetica: Picks ao vivo e
 * Agente de futebol sao os unicos que custam por assinante ativo (cota da API
 * de futebol num, token de IA no outro). E' essa conta que a diferenca de
 * preco paga, e e' por isso que o corte esta' neles e nao numa contagem de
 * abas.
 */
export type PlanoDoModulo = 'free' | 'pago' | 'pro' | 'ambos'

export interface Modulo {
  Icon: LucideIcon
  titulo: string
  /** Frase da vitrine da Home. Uma linha do que o módulo faz, sem adjetivo. */
  desc: string
  plano: PlanoDoModulo
  /** Etiqueta da vitrine. Ausente = módulo que todo mundo tem. */
  tag?: { label: string; tone: BadgeTone }
}

export const MODULOS: Modulo[] = [
  {
    Icon: Crown,
    titulo: 'Picks Premium',
    desc: 'Os picks de maior confiança do dia, com mercado, odd, stake sugerida e a análise que sustenta cada um.',
    plano: 'pago',
    tag: { label: 'Pick IA', tone: 'yellow' },
  },
  {
    Icon: Gift,
    titulo: 'Dica do dia',
    desc: 'Um pick gratuito por dia, aberto para qualquer conta. Serve para conferir o método antes de assinar.',
    plano: 'ambos',
    tag: { label: 'Free', tone: 'green' },
  },
  {
    Icon: Radio,
    titulo: 'Picks ao vivo',
    desc: 'Um motor separado lê a partida em andamento e publica quando o campo desmente o que o mercado precificou.',
    plano: 'pro',
    tag: { label: 'Pro', tone: 'indigo' },
  },
  {
    Icon: Layers,
    titulo: 'Múltiplas',
    desc: 'Combinações montadas pela IA só quando todas as seleções passam no critério estatístico.',
    plano: 'pago',
    tag: { label: 'Pick IA', tone: 'blue' },
  },
  {
    Icon: Grid3x3,
    titulo: 'Bingo do Dia',
    desc: 'Uma cartela de várias pernas por dia, montada com o mesmo critério das múltiplas.',
    plano: 'pago',
    tag: { label: 'Pick IA', tone: 'blue' },
  },
  {
    Icon: Rocket,
    titulo: 'Alavancagem',
    desc: 'Sequência de odds curtas com reinvestimento do lucro, para crescimento de banca com risco controlado.',
    plano: 'pago',
    tag: { label: 'Pick IA', tone: 'orange' },
  },
  {
    Icon: Zap,
    titulo: 'Pick Boost',
    desc: 'Varre os mercados alternativos do jogo atrás da linha que a casa deixou de corrigir.',
    plano: 'pago',
    tag: { label: 'Pick IA', tone: 'blue' },
  },
  {
    Icon: UserSquare,
    titulo: 'Estatística de jogador',
    desc: 'Projeção individual por jogador, para os mercados que a maioria das casas precifica no olho.',
    plano: 'pago',
    tag: { label: 'Pick IA', tone: 'orange' },
  },
  {
    Icon: Flag,
    titulo: 'Mercado de faltas',
    desc: 'Modelo próprio para linhas de faltas, um mercado que a maioria das casas precifica com folga.',
    plano: 'pago',
    tag: { label: 'Pick IA', tone: 'purple' },
  },
  {
    Icon: ShieldHalf,
    titulo: 'Defesas de goleiro',
    desc: 'Projeção de defesas por goleiro a partir do volume de finalização esperado dos dois lados.',
    plano: 'pago',
    tag: { label: 'Pick IA', tone: 'sky' },
  },
  {
    Icon: Bot,
    titulo: 'Agente de futebol',
    desc: 'Uma IA que responde sobre qualquer jogo, mercado ou estratégia usando os dados reais do sistema.',
    plano: 'pro',
    tag: { label: 'Pro', tone: 'green' },
  },
  {
    Icon: Wallet,
    titulo: 'Gestão de banca',
    desc: 'Stake sugerida por Kelly, controle de unidade, histórico de saques e fechamento mensal automático.',
    plano: 'ambos',
  },
  {
    Icon: BarChart3,
    titulo: 'Resultados auditáveis',
    desc: 'Todo pick publicado entra no histórico público, com win rate por liga, por jogo e por mês.',
    plano: 'ambos',
  },
  {
    Icon: CalendarDays,
    titulo: 'Agenda de jogos',
    desc: 'Todos os jogos das ligas cobertas, marcando quais já foram analisados e quais têm pick.',
    plano: 'ambos',
  },
]

/** O que entra na coluna Free · o que o módulo entrega sem assinatura. */
export const MODULOS_FREE = MODULOS.filter(m => m.plano === 'free' || m.plano === 'ambos')
/** O que o Pick IA abre, e que o Pick IA Pro também tem. */
export const MODULOS_PAGOS = MODULOS.filter(m => m.plano === 'pago')
/** O que só o Pick IA Pro abre. */
export const MODULOS_PRO = MODULOS.filter(m => m.plano === 'pro')
/** Tudo que qualquer assinatura abre · a lista do checkout do plano de topo. */
export const MODULOS_ASSINATURA = [...MODULOS_PAGOS, ...MODULOS_PRO]

/*
 * Pagamento avulso, e não assinatura recorrente.
 *
 * Não é escolha de texto: o backend cria uma `preference` do MercadoPago
 * (routers/payments.py), que cobra uma vez. Não existe `preapproval`, então não
 * existe cobrança automática no mês seguinte · o acesso simplesmente vence.
 *
 * Isso estava em lugar nenhum do site, e é a objeção mais comum de quem assina
 * qualquer coisa no Brasil. A resposta é favorável ao produto, então ela tem
 * que aparecer onde a decisão acontece: nos planos e no checkout.
 *
 * Se um dia a cobrança virar recorrente, este texto tem que sair junto no mesmo
 * commit. É por isso que ele mora aqui, e não solto dentro de duas telas.
 */
export const SEM_RENOVACAO_AUTOMATICA =
  'Pagamento único, sem renovação automática. O acesso vence na data e você decide se renova.'
