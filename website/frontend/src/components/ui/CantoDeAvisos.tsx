import type { ReactNode } from 'react'

/*
 * O CANTO DOS AVISOS DE JOGO (11/10/2026, pedido do usuário).
 *
 * Pick ao vivo e resultado (GREEN/RED) são EVENTOS de jogo: chegam no meio da
 * navegação e pedem um olhar rápido. Eles saíram da PilhaDeAvisos (faixa
 * centralizada no rodapé, que é dos convites: notificação, e-mail, plano) e
 * moram aqui, num cartão quadrado no canto de cima.
 *
 * POR QUE EM CIMA, E NÃO NO RODAPÉ
 * No celular o rodapé já tem dono: a barra inferior, o botão do Agente e a
 * própria pilha de convites. Em cima, logo abaixo do cabeçalho (h-16), o
 * cartão não briga com o polegar nem cobre a navegação. No desktop é o canto
 * onde todo sistema operacional põe notificação · o olho já procura ali.
 *
 * No celular o cartão ocupa a largura menos as margens de 16px; do `sm` pra
 * cima ele encosta à direita, com largura fixa (ver CartaoDeAviso).
 */
export default function CantoDeAvisos({ children }: { children: ReactNode }) {
  return (
    <div
      data-canto-avisos
      /* Acima do cabeçalho (z-50) e da pilha do rodapé (9990), abaixo dos
         modais. `pointer-events-none` aqui e `auto` no cartão: a faixa vazia
         não pode comer o clique da página. */
      className="fixed inset-x-4 sm:left-auto sm:right-5 z-[9992] flex flex-col items-stretch sm:items-end
                 gap-3 pointer-events-none"
      style={{ top: 'calc(4rem + 0.75rem + env(safe-area-inset-top))' }}
    >
      {children}
    </div>
  )
}
