import { useEffect, useRef, useState } from 'react'
import { cn } from '../../lib/cn'

/*
 * Fita que passa sozinha.
 *
 * A fita SEMPRE anda. Para isso o trilho precisa ser mais largo que a tela, e
 * é aí que mora a única decisão difícil deste arquivo: quando a lista real não
 * enche a largura, alguém tem que repetir alguma coisa.
 *
 * A versão original repetia até passar de 12 itens · número escolhido no olho.
 * Com 8 ligas cadastradas isso punha a mesma liga quatro vezes no trilho, às
 * vezes duas delas visíveis juntas, e lia como lista curta sendo esticada.
 * Depois eu tentei o extremo oposto: não coube, não anda. Também errado ·
 * o movimento é parte do desenho, e a fita parada vira uma lista torta.
 *
 * O certo é repetir o MÍNIMO que faz o trilho cobrir a tela, medido, e nunca
 * mais que isso. Com lista longa esse mínimo é 1, ou seja, nenhuma repetição:
 * cada item aparece uma vez e o resto já está fora da tela. Com lista curta,
 * repete duas vezes em vez de quatro. A conta é `ceil(largura da caixa /
 * largura da lista)`, e ela se refaz sozinha quando a tela muda de tamanho.
 *
 * Duas armadilhas que já custaram caro aqui:
 *
 * · A emenda saltava a cada volta. Os dois trilhos eram irmãos num flex com
 *   `gap`, e cada um animava -50% da PRÓPRIA largura · um quarto do conjunto,
 *   e ainda sem contar o vão entre eles. O espaçamento é `padding-right` em
 *   cada item justamente por isso: assim a largura total é exatamente duas
 *   cópias e o -50% cai no ponto certo. Com `gap`, o último item de cada cópia
 *   não ganha vão depois dele e a conta fecha meio espaçamento errada.
 *
 * · A velocidade dependia da quantidade · eram 28s para dar a volta, fossem 5
 *   itens ou 30. O parâmetro é pixel por segundo e a duração sai da medida.
 */

export default function Marquee({
  items,
  className,
  reverse = false,
  /** Espaçamento entre itens, como classe de padding-right (ver acima). */
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
  const [vezes, setVezes] = useState(1)
  const [duracao, setDuracao] = useState(0)
  const [semMovimento, setSemMovimento] = useState(false)

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const ler = () => setSemMovimento(mq.matches)
    ler()
    mq.addEventListener('change', ler)
    return () => mq.removeEventListener('change', ler)
  }, [])

  useEffect(() => {
    const c = caixa.current
    const um = copia.current
    if (!c || !um) return

    /*
     * Mede a primeira cópia e divide por `vezes` para chegar na largura de uma
     * passada da lista. Medir o trilho inteiro não serviria: ele dobra quando
     * a segunda cópia entra, e a medida realimentaria a própria decisão.
     */
    const medir = () => {
      const copiaLarga = um.scrollWidth
      if (copiaLarga === 0) return
      const umaLista = copiaLarga / vezes
      const precisa = Math.max(1, Math.ceil((c.clientWidth + 1) / umaLista))
      setDuracao((umaLista * precisa) / speed)
      setVezes(v => (v === precisa ? v : precisa))
    }

    medir()
    const ro = new ResizeObserver(medir)
    ro.observe(c)
    ro.observe(um)
    return () => ro.disconnect()
  }, [items.length, speed, vezes])

  const andando = !semMovimento && duracao > 0
  const linha = 'flex w-max items-center'

  // A lista repetida `vezes`. O que passa de uma volta é enfeite de largura,
  // não conteúdo novo · o leitor de tela anuncia a lista uma vez só.
  const umaCopia = (chave: string, oculto: boolean, ref?: React.Ref<HTMLDivElement>) => (
    <div ref={ref} className={cn(linha, 'shrink-0')} aria-hidden={oculto || undefined}>
      {Array.from({ length: vezes }).map((_, volta) =>
        items.map((item, i) => (
          <div
            key={`${chave}-${volta}-${i}`}
            className={cn('shrink-0', spacing, !andando && 'last:pr-0')}
            aria-hidden={volta > 0 || undefined}
          >
            {item}
          </div>
        )),
      )}
    </div>
  )

  return (
    <div
      ref={caixa}
      className={cn(
        'group relative flex overflow-hidden',
        // Movimento reduzido no sistema: fica parada e arrastável com o dedo.
        !andando && 'overflow-x-auto scrollbar-none',
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
        )}
        style={andando ? { animationDuration: `${duracao}s` } : undefined}
      >
        {umaCopia('a', false, copia)}
        {andando && umaCopia('b', true)}
      </div>
    </div>
  )
}
