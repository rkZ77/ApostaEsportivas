/*
 * O que o provider precisa saber sobre o tour sem baixar o tour.
 *
 * `OnboardingContext` entra no chunk principal (ele decide se o tour abre) e o
 * overlay é `lazy()`. Se o provider importasse `steps.tsx` para contar os
 * passos, arrastaria junto o framer-motion e os ícones do tour inteiro para o
 * caminho crítico de toda página · o mesmo motivo pelo qual GlobalModals saiu
 * de App.tsx em 14/08. Daí este arquivo.
 */

/**
 * O que muda o roteiro de uma conta para outra.
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
}

/** Passos que toda conta vê. */
export const PASSOS_FIXOS = 7

/**
 * Maior roteiro possível. É o teto que o backend valida em `tutorial_step`.
 * Mudar aqui exige mudar `TUTORIAL_TOTAL_STEPS` em routers/personal.py · há
 * teste travando os dois juntos.
 */
export const MAX_PASSOS = 8

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

export function totalDePassos(ctx: ContextoTour): number {
  return PASSOS_FIXOS + (passoDoEmailEntra(ctx) ? 1 : 0)
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
