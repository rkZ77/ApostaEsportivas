import type { ReactNode } from 'react'

/*
 * ONDE OS AVISOS APARECEM · um lugar só.
 *
 * O PROBLEMA (medido no código, 2026-09-10)
 * -----------------------------------------
 * Cinco avisos flutuantes se posicionavam cada um por conta própria, e três
 * deles reivindicavam LITERALMENTE a mesma faixa da tela:
 *
 *   LivePickToast      bottom-24   z-[9995]
 *   PlanUpsellToast    bottom-24   z-[9990]
 *   VerifyEmailBanner  bottom-24   z-[9990]
 *   PushPromptBanner   bottom-40   z-[9990]
 *   ErrorToast         bottom-6    z-[9999]   (em cima do banner de cookies)
 *
 * Dois deles com o MESMO z-index: qual cobria qual dependia da ordem em que o
 * React montou os dois naquele instante, ou seja, do acaso. Cada arquivo tinha
 * um comentário explicando de quem ele estava desviando -- combinações
 * negociadas aos pares, que só se sustentavam enquanto ninguém aparecesse
 * junto de um terceiro.
 *
 * A CORREÇÃO não é mais um z-index: é parar de cada aviso escolher onde fica.
 * Aqui existe UMA pilha no rodapé, e os avisos são filhos dela. Dois na tela
 * ao mesmo tempo empilham em vez de se cobrir, e a ordem é a ordem em que
 * estão escritos no App -- explícita, não emergente.
 *
 * A FOLGA DE BAIXO tem dois donos:
 *   - o botão flutuante do Agente, que mora no canto e não se move;
 *   - o banner de cookies, que é uma barra de rodapé inteira quando aparece.
 * O primeiro é constante e está no padding. O segundo avisa por
 * `--aviso-offset` (ver CookieBanner), porque só ele sabe se está na tela.
 */
export default function PilhaDeAvisos({ children }: { children: ReactNode }) {
  return (
    <div
      /* `pointer-events-none` no contêiner e `auto` em cada cartão: a pilha
         ocupa a largura toda pra centralizar, e sem isso essa faixa invisível
         comeria os cliques da página atrás dela. */
      className="fixed inset-x-0 bottom-0 z-[9990] flex flex-col items-center gap-2 px-4
                 pointer-events-none"
      style={{
        /* 5.5rem no celular é a altura do botão do Agente mais respiro · era
           essa a conta por trás do `bottom-24` que cada aviso repetia. */
        paddingBottom:
          'calc(var(--aviso-offset, 0px) + 5.5rem + env(safe-area-inset-bottom))',
      }}
    >
      {children}
    </div>
  )
}
