import type { MouseEvent } from 'react'

/*
 * Fechar o modal ao tocar no fundo escuro · SÓ quando o clique começa E
 * termina no fundo (14/10/2026, pedido do usuário).
 *
 * Com `onClick={fechar}` puro, selecionar o texto de um campo arrastando o
 * mouse e soltar fora da caixa fechava a tela: o navegador manda o `click`
 * pro ancestral comum de onde apertou e de onde soltou, que é o fundo.
 * A marca fica no próprio elemento (dataset), e não num estado: arrastar não
 * pode depender de render.
 */
export function fecharNoFundo(fechar: () => void) {
  return {
    onMouseDown: (e: MouseEvent<HTMLElement>) => {
      e.currentTarget.dataset.fundo = e.target === e.currentTarget ? '1' : ''
    },
    onClick: (e: MouseEvent<HTMLElement>) => {
      const fundo = e.currentTarget.dataset.fundo === '1' && e.target === e.currentTarget
      e.currentTarget.dataset.fundo = ''
      if (fundo) fechar()
    },
  }
}
