/*
 * O convite de plano, num lugar só.
 *
 * Ele aparece em dois lugares agora: o aviso no rodapé (PlanUpsellToast) e o
 * item da Central de Notificações. Com a decisão do estado e a cópia repetidas
 * nos dois, bastava mexer num para o sino passar a dizer uma coisa e o aviso
 * outra sobre a mesma conta.
 *
 * Era uma faixa larga no topo da página (PlanUpsellBar, até 21/08). Ela empurrava
 * a página inteira para baixo em TODA tela do app, para uma conversa que não é
 * do conteúdo que a pessoa foi ver. No rodapé ela continua à vista sem tomar
 * uma linha do topo, e o texto passou a ser string pura em vez de JSX
 * justamente para caber também no sino, sem uma segunda redação.
 */

export const SNOOZE_KEY = 'pickia_plan_upsell_snooze'
const SNOOZE_MS = 24 * 60 * 60 * 1000

/**
 * Id do item sintético no sino.
 *
 * Negativo de propósito: os ids reais vêm do Postgres e são positivos, então
 * nada colide, e quem for marcar como lido consegue distinguir na hora um item
 * que existe no servidor de um que só existe neste navegador (este aqui não tem
 * linha em `notifications` para dar POST).
 */
export const ID_NOTIFICACAO_PLANO = -1

export interface ConvitePlano {
  titulo: string
  texto: string
  cta: string
  to: string
  /** Amarelo é o tom de VIP no site inteiro; âmbar puxa a urgência do trial. */
  tone: 'yellow' | 'amber'
}

interface ContaMinima {
  plan?: string | null
  email_verified?: boolean | null
  trial_used?: boolean | null
}

export function planoAdiado(): boolean {
  const raw = localStorage.getItem(SNOOZE_KEY)
  const ts = raw ? Number(raw) : 0
  return Number.isFinite(ts) && Date.now() < ts
}

export function adiarPlano(): void {
  localStorage.setItem(SNOOZE_KEY, String(Date.now() + SNOOZE_MS))
}

/**
 * O convite desta conta, ou null quando não há o que dizer.
 *
 * Três estados, nesta ordem de precedência: free, trial acabando, VIP perto de
 * expirar. VIP com folga e admin não veem nada.
 *
 * O free que ainda pode ganhar o trial confirmando o e-mail também não vê: para
 * ele existe um convite melhor (VerifyEmailBanner, 2 dias de VIP de graça), e
 * dois avisos empilhados no rodapé pedindo a mesma coisa por caminhos
 * diferentes é o tipo de ruído que a pessoa aprende a não ler.
 */
export function convitePlano(
  user: ContaMinima | null | undefined,
  daysUntilExpiry: number | null,
  isAdmin: boolean,
): ConvitePlano | null {
  if (!user || isAdmin) return null

  const dias = daysUntilExpiry
  const prazo = dias == null ? null
    : dias <= 0 ? 'hoje'
    : dias === 1 ? 'amanhã'
    : `em ${dias} dias`

  if (user.plan === 'free') {
    const podeGanharTrial = user.email_verified === false && user.trial_used !== true
    if (podeGanharTrial) return null
    return {
      titulo: 'Você está no plano gratuito',
      texto: '1 pick por dia. O VIP abre todos.',
      cta: 'Conhecer o VIP',
      to: '/planos',
      tone: 'yellow',
    }
  }

  if (user.plan === 'trial') {
    return {
      titulo: prazo ? `Seu teste do VIP termina ${prazo}` : 'Seu teste do VIP está em andamento',
      texto: 'Assine para não perder o acesso.',
      cta: 'Assinar VIP',
      to: '/checkout',
      tone: 'amber',
    }
  }

  if (user.plan === 'vip' && dias != null && dias <= 5) {
    return {
      titulo: `Seu VIP expira ${prazo}`,
      texto: 'Renove para continuar com todos os picks.',
      cta: 'Renovar',
      to: '/planos',
      tone: 'yellow',
    }
  }

  return null
}
