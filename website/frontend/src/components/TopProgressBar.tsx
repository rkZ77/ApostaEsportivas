import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { assinarNavegacao, assinarPendentes, pendentesAgora } from '../services/progressBus'

/*
 * Barra de carregamento no topo da página, no estilo YouTube/Kick.
 *
 * QUANDO ELA APARECE
 * ------------------
 * Na NAVEGAÇÃO, não a cada requisição. O site faz polling em várias telas
 * (ver o comentário em services/progressBus.ts) · uma barra por XHR ficaria
 * piscando sozinha enquanto o usuário lê a tela parado, que é exatamente o
 * oposto do que a barra comunica.
 *
 * Ela começa quando a rota muda e só fecha quando a tela nova parou de buscar
 * dados, então cobre as duas esperas que o usuário percebe como uma só: baixar
 * o chunk da página (todas as rotas são lazy em App.tsx) e carregar o conteúdo
 * dela.
 *
 * COMO ELA ANDA
 * -------------
 * Não dá pra saber a fração real do que falta, então ela cresce em direção a
 * 90% sempre pegando uma fatia do que resta · anda rápido no começo e vai
 * desacelerando, sem nunca encostar no fim antes da hora. Ao terminar, salta
 * pra 100% e some. É a mesma ilusão que o nprogress popularizou: o que importa
 * é comunicar "estou trabalhando", não medir.
 */

/** Fatia do que falta até o teto, consumida a cada tique. */
const CRESCIMENTO = 0.14
/** Onde ela trava enquanto a resposta não chega. */
const TETO = 90
const TIQUE_MS = 180
/** Janela pra tela nova disparar as chamadas dela antes de olharmos o contador
 *  · sem isso a barra fecharia no mesmo quadro em que abriu, porque no
 *  instante da troca de rota ainda não há nada em voo. */
const ESPERA_INICIAL_MS = 200
/** Piso de tempo visível: rota estática (termos, privacidade) não busca nada,
 *  e uma barra que aparece e some no mesmo piscar incomoda mais que ajuda. */
const TEMPO_MINIMO_MS = 400
/** Teto absoluto: rede travada não pode deixar a barra eterna na tela. */
const TEMPO_MAXIMO_MS = 10_000
/** Tempo pro salto até 100% ser visto antes do fade. */
const SAIDA_MS = 260

export default function TopProgressBar() {
  const { pathname } = useLocation()
  const [progresso, setProgresso] = useState(0)
  const [visivel, setVisivel] = useState(false)
  const primeiraRota = useRef(true)
  /* Troca de aba dentro de uma mesma rota (ver sinalizarNavegacao). Um contador
     em vez de um booleano: duas trocas seguidas precisam reiniciar o ciclo. */
  const [gatilhoManual, setGatilhoManual] = useState(0)

  useEffect(() => assinarNavegacao(() => setGatilhoManual(g => g + 1)), [])

  useEffect(() => {
    /* A primeira renderização já tem o Suspense de tela cheia do App. Somar a
       barra ali só polui o carregamento inicial, que não é navegação. */
    if (primeiraRota.current) {
      primeiraRota.current = false
      return
    }

    const inicio = Date.now()
    let encerrado = false
    let tique: number | undefined
    let vigia: number | undefined
    let limite: number | undefined
    let saida: number | undefined
    let desassinar: () => void = () => {}

    const limpar = () => {
      window.clearInterval(tique)
      window.clearInterval(vigia)
      window.clearTimeout(limite)
      desassinar()
    }

    const finalizar = () => {
      if (encerrado) return
      encerrado = true
      limpar()
      setProgresso(100)
      saida = window.setTimeout(() => {
        setVisivel(false)
        setProgresso(0)
      }, SAIDA_MS)
    }

    const podeFinalizar = () =>
      Date.now() - inicio >= Math.max(ESPERA_INICIAL_MS, TEMPO_MINIMO_MS) &&
      pendentesAgora() === 0

    setVisivel(true)
    setProgresso(8)

    tique = window.setInterval(() => {
      setProgresso(p => p + (TETO - p) * CRESCIMENTO)
    }, TIQUE_MS)

    /* Duas fontes pro mesmo fim: o contador avisa quando a última resposta
       chega, e o vigia cobre a rota que nunca chegou a pedir nada. */
    desassinar = assinarPendentes(() => { if (podeFinalizar()) finalizar() })
    vigia = window.setInterval(() => { if (podeFinalizar()) finalizar() }, 80)
    limite = window.setTimeout(finalizar, TEMPO_MAXIMO_MS)

    return () => {
      encerrado = true
      limpar()
      window.clearTimeout(saida)
    }
  }, [pathname, gatilhoManual])

  if (!visivel) return null

  return (
    <div
      className="fixed inset-x-0 top-0 z-[100] h-[3px] pointer-events-none"
      /* Decorativa: o conteúdo que está chegando é anunciado pela própria
         página, e um progressbar sem valor real só faria barulho no leitor. */
      aria-hidden="true"
    >
      {/* Verde chapado, sem brilho. A primeira versão tinha um box-shadow de
          10px que dava efeito neon · o movimento da barra já diz que algo está
          carregando, e o brilho só competia com o conteúdo da página. */}
      <div
        className="h-full bg-accent transition-[width,opacity] duration-200 ease-out motion-reduce:transition-none"
        style={{
          width: `${progresso}%`,
          opacity: progresso >= 100 ? 0 : 1,
        }}
      />
    </div>
  )
}
