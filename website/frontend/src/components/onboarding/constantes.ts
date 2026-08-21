/*
 * O que o provider precisa saber sobre o tour sem baixar o tour.
 *
 * `OnboardingContext` entra no chunk principal (ele decide se o tour abre) e o
 * overlay é `lazy()`. Se o provider importasse `steps.tsx` para contar os
 * passos, arrastaria junto o framer-motion e os ícones do tour inteiro para o
 * caminho crítico de toda página · o mesmo motivo pelo qual GlobalModals saiu
 * de App.tsx em 14/08. Daí este arquivo de uma linha.
 *
 * `steps.tsx` confere o número no import e avisa no console em dev se os dois
 * saírem de sincronia.
 */
export const TOTAL_PASSOS = 7
