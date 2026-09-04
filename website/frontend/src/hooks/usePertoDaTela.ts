import { useEffect, useRef, useState } from 'react'

/**
 * `true` quando o elemento chega perto da viewport · e nunca volta a `false`.
 *
 * POR QUE ISTO EXISTE. A Home abria seis chamadas públicas no mesmo instante,
 * três delas de seções que estavam abaixo da dobra. Medidas uma a uma essas
 * rotas custam de 0,4s a 1,9s; medidas como o navegador realmente as faz, o
 * PageSpeed de 04/09 anotou de 4,6s a 6,3s cada · o servidor roda com um
 * worker só, então elas viram fila e a fila é o próprio tempo de resposta.
 *
 * Adiar o que está fora da tela não é só economia de banda: é tirar da fila as
 * chamadas que ninguém está esperando ver, para as três de cima chegarem antes.
 *
 * A folga padrão é generosa de propósito. O objetivo NÃO é economizar request
 * (quem rola vai fazê-lo de qualquer jeito), é tirá-lo do congestionamento do
 * primeiro segundo · então ele deve disparar bem antes de a seção aparecer,
 * para que ela nunca seja vista vazia.
 *
 * Sem IntersectionObserver (jsdom, navegador antigo) devolve `true` na hora, o
 * que é exatamente o comportamento anterior a este hook.
 */
export function usePertoDaTela<T extends HTMLElement>(margem = '400px') {
  const alvo = useRef<T>(null)
  const [perto, setPerto] = useState(false)

  useEffect(() => {
    const el = alvo.current
    if (!el || perto) return
    if (typeof IntersectionObserver === 'undefined') {
      setPerto(true)
      return
    }

    const io = new IntersectionObserver(
      ([entrada]) => {
        if (!entrada.isIntersecting) return
        setPerto(true)
        io.disconnect()
      },
      { rootMargin: margem },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [margem, perto])

  return [alvo, perto] as const
}
