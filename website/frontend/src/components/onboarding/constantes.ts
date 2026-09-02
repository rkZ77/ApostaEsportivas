/*
 * O que o provider precisa saber sobre os tours sem baixar os tours.
 *
 * `OnboardingContext` entra no chunk principal (ele decide se algum tour abre)
 * e o overlay é `lazy()`. Se o provider importasse `steps.tsx` para contar os
 * passos, arrastaria junto o framer-motion e os ícones dos roteiros inteiros
 * para o caminho crítico de toda página · o mesmo motivo pelo qual GlobalModals
 * saiu de App.tsx em 14/08. Daí este arquivo.
 */

/** Os roteiros. Espelha TOURS em backend/routers/personal.py. */
export type NomeTour = 'boas-vindas' | 'vip'

export const TOUR_BOAS_VINDAS: NomeTour = 'boas-vindas'
export const TOUR_VIP: NomeTour = 'vip'

/**
 * O que muda o roteiro de boas-vindas de uma conta para outra.
 *
 * Congelado quando o tour abre (ver OnboardingContext): confirmar o e-mail
 * numa outra aba no meio do tour tiraria um passo do meio da fila, e o número
 * "3 de 8" mudaria de significado embaixo de quem está lendo.
 */
export interface ContextoTour {
  /** Conta ainda sem e-mail confirmado. */
  emailPendente: boolean
  /** Os 2 dias de VIP ainda não foram usados. */
  trialNaMesa: boolean
  /** Conta sem telefone · não dá para avisar no WhatsApp. */
  semTelefone: boolean
}

/* 7 desde 02/09/2026.
   Saiu o passo de produto ("Ao Vivo e Boost", que tinha entrado em 01/09).

   A DIVISAO ENTRE OS DOIS ROTEIROS, que e' o motivo: toda conta ganha periodo
   de teste, entao TODA conta acaba vendo o tour do VIP. Com isso o roteiro de
   boas-vindas nao precisa (nem deve) apresentar produto: ele apresenta o SITE
   -- confirmar e-mail, configurar banca, onde ficam os picks, WhatsApp, como
   registrar e como acompanhar. Quem apresenta produto e' o tour do VIP, que
   abre quando o acesso libera. Produto citado nos dois vira a mesma explicacao
   duas vezes em poucos dias. */
/** Passos do roteiro de boas-vindas que toda conta vê. */
export const PASSOS_FIXOS = 7

/**
 * Maior roteiro de boas-vindas possível. É o teto que o backend valida em
 * `tutorial_step`. Mudar aqui exige mudar `TUTORIAL_TOTAL_STEPS` em
 * routers/personal.py · há teste travando os dois juntos.
 */
export const MAX_PASSOS = 9

/**
 * Roteiro do VIP · o que a assinatura abriu.
 *
 * Fixo, sem passo condicional: quem chega aqui acabou de ganhar acesso a tudo,
 * então todas as áreas do roteiro valem para todo mundo que o vê. Espelha
 * `VIP_TOUR_TOTAL_STEPS` no backend.
 */
/* 10 desde 02/09/2026 · entraram "Registre a aposta" e "Acompanhe sua
   evolucao", que TAMBEM existem no roteiro de boas-vindas. A repeticao e'
   deliberada (decisao do usuario): o tour de boas-vindas pode ter sido pulado,
   e sem registrar a aposta nada do que este roteiro abriu vira resultado na
   banca.

   Eram 8 desde 2026-08-28, quando o passo de "Mercados" (aba que deixou de
   existir) virou tres: picks de jogador, Pick Boost e Picks Ao Vivo.

   O numero e' literal e nao derivado do array de proposito: ele aparece no
   rodape do tour ("passo 3 de 10") e a lista e' montada em outro arquivo. */
export const TOTAL_PASSOS_VIP = 10

/**
 * O passo "Confirme seu e-mail" entra?
 *
 * Só para quem tem os 2 dias de VIP esperando do outro lado do clique. Para
 * quem já confirmou, ou já gastou o trial, ele seria uma tela pedindo uma
 * coisa que não muda nada · e o tour tem sete passos justamente porque cada um
 * precisa se pagar.
 *
 * Uma função só, usada pelo roteiro (para montar a lista) e pelo provider
 * (para contar). Duas cópias dessa condição divergem no primeiro ajuste.
 */
export function passoDoEmailEntra(ctx: ContextoTour): boolean {
  return ctx.emailPendente && ctx.trialNaMesa
}

/*
 * O passo do WhatsApp entra?
 *
 * Só para quem não tem telefone na conta. Quem entrou pelo Google costuma cair
 * aqui: o cadastro por formulário pede o número, o do Google não · e é ele que
 * o aviso de pick publicado e de pick ao vivo usa. Pedir de novo a quem já
 * preencheu seria um passo que não muda nada, e o roteiro é curto de propósito.
 */
export function passoDoWhatsAppEntra(ctx: ContextoTour): boolean {
  return ctx.semTelefone
}

export function totalDePassos(ctx: ContextoTour): number {
  return PASSOS_FIXOS
    + (passoDoEmailEntra(ctx) ? 1 : 0)
    + (passoDoWhatsAppEntra(ctx) ? 1 : 0)
}

/** Quantos passos este roteiro tem, para esta conta. */
export function totalDoTour(tour: NomeTour, ctx: ContextoTour): number {
  return tour === TOUR_VIP ? TOTAL_PASSOS_VIP : totalDePassos(ctx)
}

/**
 * O tour pedindo à página da Banca que abra o formulário DE VERDADE.
 *
 * Evento de janela, e não prop nem contexto, porque quem dispara (o balão do
 * tour, num portal no body) e quem atende (`SetupModal`, estado interno da
 * página) não se enxergam na árvore de componentes. O tour se recolhe enquanto
 * o formulário está aberto, ver `pausar` em OnboardingContext.
 */
export const EVENTO_CONFIGURAR_BANCA = 'pickia:configurar-banca'
