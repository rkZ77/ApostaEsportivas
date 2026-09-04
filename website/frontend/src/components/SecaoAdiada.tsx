import { ReactNode, Suspense, useEffect, useState } from 'react'
import { usePertoDaTela } from '../hooks/usePertoDaTela'

/*
 * Seção que só é MONTADA quando faz falta.
 *
 * Diferente do `usePertoDaTela` usado sozinho (que adia a chamada de API mas
 * monta o componente), aqui os filhos nem existem no React até a hora: nada de
 * árvore, nada de estilo calculado, nada de layout. O PageSpeed de 04/09
 * contou 2.120 elementos na Home, quase todos de seções que ninguém tinha
 * olhado ainda.
 *
 * DOIS GATILHOS, E O SEGUNDO É O QUE IMPORTA
 * ------------------------------------------
 * O óbvio é o IntersectionObserver: chegou perto, monta. Sozinho, ele tem um
 * problema sério para este site · quem NUNCA rola nunca monta, e "quem nunca
 * rola" inclui o Ctrl+F do visitante, o leitor de tela que percorre a página
 * inteira, e qualquer rastreador que renderize sem rolar. Conteúdo que só
 * existe depois de um gesto é conteúdo que pode não existir.
 *
 * Por isso o segundo gatilho: passado o carregamento, no primeiro momento
 * ocioso, tudo monta de qualquer jeito. O ganho não é deixar de montar, é
 * montar DEPOIS · fora do caminho crítico, quando o texto principal já está na
 * tela e a thread está livre. A página fica inteira em todos os casos.
 *
 * O ESPAÇO É RESERVADO ANTES
 * --------------------------
 * `alturaMinima` mantém a barra de rolagem estável e evita que o conteúdo
 * abaixo salte quando a seção nasce. Não precisa ser exata (a seção cresce
 * livremente se precisar de mais), precisa ser da mesma ordem de grandeza · os
 * valores vieram de medição no viewport de 390px, que é o público do site.
 */

/** Reserva antes do gatilho por rolagem. Generosa de propósito: a seção deve
 *  nascer antes de aparecer, nunca "durante". */
const MARGEM = '600px'

/** Espera depois do `load` antes de montar o que ninguém pediu. Tempo pra
 *  primeira tela terminar de se acomodar sem disputar thread. */
const OCIOSO_MS = 1500

export default function SecaoAdiada({
  alturaMinima,
  children,
}: {
  /** Altura reservada enquanto não montou (px). */
  alturaMinima: number
  children: ReactNode
}) {
  const [alvo, perto] = usePertoDaTela<HTMLDivElement>(MARGEM)
  const [ocioso, setOcioso] = useState(false)

  useEffect(() => {
    if (ocioso) return
    let idle: number | undefined
    const agendar = () => {
      const ric = (window as unknown as {
        requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number
      }).requestIdleCallback
      idle = ric
        ? ric(() => setOcioso(true), { timeout: 4000 })
        : window.setTimeout(() => setOcioso(true), OCIOSO_MS)
    }
    // Depois do load: antes disso a thread ainda é do primeiro paint.
    if (document.readyState === 'complete') {
      const t = window.setTimeout(agendar, OCIOSO_MS)
      return () => window.clearTimeout(t)
    }
    const aoCarregar = () => window.setTimeout(agendar, OCIOSO_MS)
    window.addEventListener('load', aoCarregar, { once: true })
    return () => {
      window.removeEventListener('load', aoCarregar)
      if (idle !== undefined) window.clearTimeout(idle)
    }
  }, [ocioso])

  const montar = perto || ocioso

  return (
    <div ref={alvo} style={montar ? undefined : { minHeight: alturaMinima }}>
      {/* O Suspense é para os filhos que chegam por `lazy()`. O fallback é
          vazio de propósito: um esqueleto aqui apareceria por um quadro em
          conexão boa e leria como defeito. O espaço já está reservado. */}
      {montar ? <Suspense fallback={null}>{children}</Suspense> : null}
    </div>
  )
}
