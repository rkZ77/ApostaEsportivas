import { useEffect, useRef, useState } from 'react'
import { cn } from '../../lib/cn'

/*
 * Fita que passa sozinha.
 *
 * Três coisas que a versão anterior errava, todas visíveis na Home:
 *
 * 1. Repetia item para encher o trilho. Quem chamava é que resolvia isso ·
 *    LeagueMarquee duplicava a lista até passar de 12 itens, então com 8 ligas
 *    cadastradas a mesma liga aparecia quatro vezes, às vezes duas delas na
 *    tela ao mesmo tempo. Lido de fora, parecia catálogo inflado. Agora, se a
 *    lista não enche a largura, a fita simplesmente NÃO anda: fica parada e
 *    centralizada, com cada item uma vez só. Não ter o que rolar é uma
 *    informação legítima, não um defeito para disfarçar.
 *
 * 2. A emenda dava um salto. Os dois trilhos eram irmãos num flex com `gap`, e
 *    cada um animava -50% da PRÓPRIA largura · ou seja, um quarto do conjunto,
 *    e ainda por cima sem contar o vão entre eles. A cada volta a fita pulava.
 *    O espaçamento agora é `padding-right` em cada item, e não `gap` no flex:
 *    assim a largura total é exatamente duas cópias, e -50% cai no ponto certo.
 *    Com `gap`, o último item de cada cópia não ganha vão depois dele e a conta
 *    fecha sempre meio espaçamento errada.
 *
 * 3. A velocidade dependia da quantidade. Era 28s para dar a volta, fossem 5
 *    itens ou 30 · quanto mais item, mais rápido corria. Agora o parâmetro é
 *    pixels por segundo e a duração sai da largura medida.
 *
 * A segunda cópia existe só enquanto a fita anda, e é ela que faz o laço não
 * ter fim. Como o trilho só anda quando é mais largo que a tela, as duas
 * cópias do mesmo item nunca ficam visíveis ao mesmo tempo.
 */

export default function Marquee({
  items,
  className,
  reverse = false,
  /** Espaçamento entre itens, como classe de padding-right (ver comentário 2). */
  spacing = 'pr-8',
  /** Pixels por segundo. Item grande pede mais lento: o olho precisa ler. */
  speed = 50,
}: {
  items: React.ReactNode[]
  className?: string
  reverse?: boolean
  spacing?: string
  speed?: number
}) {
  const caixa = useRef<HTMLDivElement>(null)
  const copia = useRef<HTMLDivElement>(null)
  const [cabe, setCabe] = useState(true)
  const [andando, setAndando] = useState(false)
  const [duracao, setDuracao] = useState(0)

  useEffect(() => {
    const c = caixa.current
    const um = copia.current
    if (!c || !um) return

    const semMovimento = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    // Mede sempre a PRIMEIRA cópia, nunca o trilho: o trilho dobra de tamanho
    // quando a animação liga, e medir ele realimentaria a própria decisão.
    const medir = () => {
      const largura = um.scrollWidth
      const coube = largura <= c.clientWidth + 4
      setDuracao(largura / speed)
      setCabe(coube)
      setAndando(!semMovimento && !coube)
    }

    medir()
    const ro = new ResizeObserver(medir)
    ro.observe(c)
    ro.observe(um)
    return () => ro.disconnect()
  }, [items.length, speed])

  const linha = 'flex w-max items-center'

  return (
    <div
      ref={caixa}
      className={cn(
        'group relative flex overflow-hidden',
        // Maior que a tela e parada · só acontece com movimento reduzido
        // ligado no sistema. Aí ainda tem que dar para arrastar com o dedo.
        !cabe && !andando && 'overflow-x-auto scrollbar-none',
        andando && '[mask-image:linear-gradient(90deg,transparent,black_6%,black_94%,transparent)]',
        className,
      )}
    >
      <div
        className={cn(
          linha,
          andando && 'animate-marquee',
          reverse && andando && '[animation-direction:reverse]',
          // Pausa sob o cursor e sob o dedo: no toque o :hover gruda, que aqui
          // é justamente o comportamento útil · quem encostou quer ler.
          andando && 'group-hover:[animation-play-state:paused]',
          // Sem nada para rolar, a fita fica centrada em vez de encostada à
          // esquerda com um vazio do lado direito.
          cabe && 'mx-auto',
        )}
        style={andando ? { animationDuration: `${duracao}s` } : undefined}
      >
        {/* Parada, o espaçamento do último item vira um vão morto que desloca
            o conjunto centralizado. Andando ele é obrigatório: é o que fecha
            a conta do -50%. */}
        <div ref={copia} className={cn(linha, 'shrink-0')}>
          {items.map((item, i) => (
            <div key={`a-${i}`} className={cn('shrink-0', spacing, cabe && 'last:pr-0')}>{item}</div>
          ))}
        </div>

        {andando && (
          <div className={cn(linha, 'shrink-0')} aria-hidden="true">
            {items.map((item, i) => (
              <div key={`b-${i}`} className={cn('shrink-0', spacing)}>{item}</div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
