import { useCallback, useEffect, useRef, useState } from 'react'
import { cn } from '../../lib/cn'

/*
 * Fita que passa sozinha · e que também aceita ser empurrada com o dedo.
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
 * POR QUE O MOVIMENTO SAIU DO CSS
 * -------------------------------
 * Antes era uma `animation` de `translateX(-50%)`. Anda liso e não custa nada,
 * mas é uma via de mão única: o trilho não é rolável, então não havia como
 * empurrar a fita para procurar um item específico. Na prática isso obrigava a
 * ESPERAR o item chegar · e com card grande, como o dos próximos jogos, a
 * espera é de vários segundos.
 *
 * Agora quem move é a rolagem nativa, empurrada quadro a quadro. Com isso o
 * dedo, o trackpad e a barra de rolagem funcionam de graça, e o laço só
 * precisa devolver a posição pro começo quando passa de uma cópia · a emenda
 * é invisível porque a segunda cópia é idêntica à primeira.
 *
 * Três armadilhas que já custaram caro aqui:
 *
 * · A emenda saltava a cada volta. O espaçamento é `padding-right` em cada
 *   item, e não `gap` no flex, justamente por isso: assim a largura de uma
 *   cópia é exata e o ponto de retorno cai certo. Com `gap`, o último item de
 *   cada cópia não ganha vão depois dele e a conta fecha meio espaçamento
 *   errada.
 *
 * · A velocidade dependia da quantidade · eram 28s para dar a volta, fossem 5
 *   itens ou 30. O parâmetro é pixel por segundo, e não duração.
 *
 * · Arrastar não pode virar clique. Depois de 6px de movimento o ponteiro está
 *   navegando, não escolhendo, e o clique que vem no fim do arrasto é
 *   engolido · senão soltar o dedo em cima de um card abriria o card.
 */

/** Movimento em px a partir do qual o gesto é arrasto, e não clique. */
const LIMIAR_ARRASTO = 6
/** Silêncio depois do dedo sair antes de a fita voltar a andar. */
const RETOMADA_MS = 1200

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
  const [semMovimento, setSemMovimento] = useState(false)
  const [arrastando, setArrastando] = useState(false)

  /* Largura de UMA cópia do trilho · o ponto onde a rolagem volta pro começo.
     Fica em ref, e não em estado, porque quem lê é o laço de animação: passar
     por estado faria o laço remontar a cada medida. */
  const larguraCopia = useRef(0)
  const pausado = useRef(false)
  /*
   * Cursor em cima. Separado de `pausado` de propósito.
   *
   * Os dois motivos de parar têm durações diferentes: o arrasto acaba num
   * instante e libera por temporizador, o cursor parado em cima dura o tempo
   * que a pessoa quiser. Com uma variável só, terminar um arrasto religava a
   * fita 1,2s depois mesmo com o cursor ainda parado ali · e quem estava lendo
   * via o card sair de baixo do próprio ponteiro.
   */
  const sobMouse = useRef(false)
  const retomada = useRef<number | undefined>(undefined)

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
      larguraCopia.current = umaLista * precisa
      setVezes(v => (v === precisa ? v : precisa))
    }

    medir()
    const ro = new ResizeObserver(medir)
    ro.observe(c)
    ro.observe(um)
    return () => ro.disconnect()
  }, [items.length, vezes])

  const andando = !semMovimento && items.length > 0

  /* Devolve a rolagem pra dentro da primeira cópia. Vale pro laço e pro dedo:
     quem arrasta até o fim do trilho reencontra o começo sem esbarrar numa
     parede. */
  const normalizar = useCallback(() => {
    const c = caixa.current
    const w = larguraCopia.current
    if (!c || w <= 0) return
    if (c.scrollLeft >= w) c.scrollLeft -= w
    else if (c.scrollLeft < 0) c.scrollLeft += w
  }, [])

  // Laço de animação. Empurra a rolagem em px/s, respeitando o relógio real ·
  // `deltaTempo` em vez de um passo fixo por quadro, senão a fita anda mais
  // devagar em tela de 60Hz que em 120Hz.
  useEffect(() => {
    if (!andando) return
    const c = caixa.current
    if (!c) return

    // Em `reverse` a fita nasce no fim da primeira cópia: sem isso ela
    // encostaria no zero no primeiro quadro e não teria pra onde voltar.
    if (reverse && c.scrollLeft === 0 && larguraCopia.current > 0) {
      c.scrollLeft = larguraCopia.current
    }

    let quadro = 0
    let anterior = performance.now()
    const passo = (agora: number) => {
      const dt = Math.min((agora - anterior) / 1000, 0.1)  // aba escondida volta com salto
      anterior = agora
      if (!pausado.current && !sobMouse.current && !document.hidden && larguraCopia.current > 0) {
        c.scrollLeft += (reverse ? -1 : 1) * speed * dt
        normalizar()
      }
      quadro = requestAnimationFrame(passo)
    }
    quadro = requestAnimationFrame(passo)
    return () => cancelAnimationFrame(quadro)
  }, [andando, reverse, speed, normalizar])

  useEffect(() => () => window.clearTimeout(retomada.current), [])

  const pausar = () => { pausado.current = true; window.clearTimeout(retomada.current) }
  const soltar = (atraso = 0) => {
    window.clearTimeout(retomada.current)
    retomada.current = window.setTimeout(() => { pausado.current = false }, atraso)
  }

  /*
   * Arrasto com o ponteiro.
   *
   * O toque e o trackpad já rolam sozinhos (é `overflow-x-auto`), então isto
   * existe pro MOUSE, que numa caixa rolável só teria a barra. `setPointerCapture`
   * mantém o gesto vivo mesmo se o cursor sair da fita no meio do arrasto.
   */
  const inicio = useRef({ x: 0, scroll: 0, moveu: false })

  const aoPressionar = (ev: React.PointerEvent<HTMLDivElement>) => {
    if (ev.pointerType === 'mouse' && ev.button !== 0) return
    pausar()
    inicio.current = { x: ev.clientX, scroll: caixa.current?.scrollLeft ?? 0, moveu: false }
    if (ev.pointerType === 'mouse') {
      setArrastando(true)
      caixa.current?.setPointerCapture(ev.pointerId)
    }
  }

  const aoMover = (ev: React.PointerEvent<HTMLDivElement>) => {
    const c = caixa.current
    if (!c || !c.hasPointerCapture?.(ev.pointerId)) return
    const andou = ev.clientX - inicio.current.x
    if (Math.abs(andou) > LIMIAR_ARRASTO) inicio.current.moveu = true
    c.scrollLeft = inicio.current.scroll - andou
    normalizar()
  }

  const aoSoltar = (ev: React.PointerEvent<HTMLDivElement>) => {
    setArrastando(false)
    caixa.current?.releasePointerCapture?.(ev.pointerId)
    soltar(RETOMADA_MS)
  }

  // Clique que fecha um arrasto não é escolha, é o fim do gesto.
  const aoClicar = (ev: React.MouseEvent<HTMLDivElement>) => {
    if (!inicio.current.moveu) return
    ev.preventDefault()
    ev.stopPropagation()
    inicio.current.moveu = false
  }

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
      onPointerDown={aoPressionar}
      onPointerMove={aoMover}
      onPointerUp={aoSoltar}
      onPointerCancel={aoSoltar}
      onClickCapture={aoClicar}
      /* Só o dedo pausa e retoma sozinho. O mouse usa pointerdown/up porque no
         desktop passar por cima sem querer não deveria travar a fita para
         sempre · quem quer ler para em cima, e é o `group-hover` que resolve. */
      onMouseEnter={() => { sobMouse.current = true }}
      onMouseLeave={() => { sobMouse.current = false }}
      onTouchStart={pausar}
      onTouchEnd={() => soltar(RETOMADA_MS)}
      onScroll={normalizar}
      className={cn(
        'group relative flex overflow-x-auto overscroll-x-contain scrollbar-none',
        // `touch-pan-x`: o gesto horizontal é da fita, o vertical continua
        // rolando a página · sem isso, arrastar em diagonal no celular trava a
        // rolagem da página inteira.
        'touch-pan-x select-none',
        arrastando ? 'cursor-grabbing' : 'cursor-grab',
        andando && '[mask-image:linear-gradient(90deg,transparent,black_6%,black_94%,transparent)]',
        className,
      )}
    >
      <div className={linha}>
        {umaCopia('a', false, copia)}
        {andando && umaCopia('b', true)}
      </div>
    </div>
  )
}
