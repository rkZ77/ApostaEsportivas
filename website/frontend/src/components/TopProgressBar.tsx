import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { assinarLentidao, assinarNavegacao, assinarPendentes, pendentesAgora } from '../services/progressBus'

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
/** Teto absoluto: rede travada não pode deixar a barra eterna na tela.
 *
 *  Eram 10s, e 10s de barra andando é a tela dizendo "ainda estou carregando"
 *  muito depois de a página já estar lá · quem lê isso conclui que o site é
 *  lento, não que uma requisição ficou pendurada. */
const TEMPO_MAXIMO_MS = 6_000
/** Quanto tempo a fila precisa ficar VAZIA pra a barra aceitar que acabou.
 *
 *  É o que absorve a cascata: dado A chega, componente B monta e pede o dele.
 *  Curto demais e a barra fecha no respiro entre os dois; longo demais e ela
 *  fica no ar depois de a tela já estar pronta. */
const SILENCIO_MS = 350

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

  /* O terceiro caso: a tela já está montada e uma consulta está demorando.
   *
   * SÓ ABRE UM CICLO NOVO SE NÃO HOUVER UM RODANDO (corrigido em 2026-09-04, no
   * mesmo dia). Sem esta guarda cada disparo remontava o efeito, a barra voltava
   * a 8% e recomeçava · numa tela com várias consultas lentas em sequência ela
   * ia e voltava várias vezes, que é o oposto de "acabou a barra, carregou
   * tudo". Uma rajada nova enquanto a barra está no ar NÃO reinicia: ela é
   * absorvida pelo ciclo que já está correndo, porque o ciclo só fecha quando
   * não há mais nada em voo. */
  const rodando = useRef(false)
  useEffect(() => assinarLentidao(() => {
    if (!rodando.current) setGatilhoManual(g => g + 1)
  }), [])

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
      rodando.current = false
      limpar()
      setProgresso(100)
      saida = window.setTimeout(() => {
        setVisivel(false)
        setProgresso(0)
      }, SAIDA_MS)
    }

    /* O QUE JÁ ESTAVA EM VOO NÃO SEGURA A BARRA.
     *
     * Várias telas fazem polling em segundo plano (o sino, o "está ao vivo?",
     * o Admin). Esperar o contador chegar a ZERO fazia a barra da navegação
     * ficar refém de uma requisição que não tem nada a ver com ela: bastava um
     * poll estar no ar no instante do clique para a barra continuar andando
     * depois de a tela nova já estar pronta -- até o teto de tempo, no pior
     * caso.
     *
     * O que interessa é o que a tela NOVA pediu. As pendentes de antes entram
     * como piso: a barra fecha quando o contador volta ao nível em que estava
     * quando a navegação começou. */
    const herdadas = pendentesAgora()

    /* SILÊNCIO CONTÍNUO, e não um instante de silêncio.
     *
     * A condição era só "o contador voltou ao nível de antes". Entre uma
     * resposta e o pedido seguinte existe um respiro de milissegundos, e nesse
     * respiro a barra fechava · a requisição seguinte então abria outra, e o
     * usuário via a barra ir e voltar numa tela que ainda estava carregando.
     *
     * Exigindo que a fila fique vazia por um tempo CONTÍNUO, uma tela que pede
     * em cascata (o dado A chega, o componente B monta e pede o dele) fecha uma
     * vez só, no fim de tudo. É o que faz "a barra acabou" significar
     * "carregou". */
    let quietoDesde: number | null = null

    const podeFinalizar = () => {
      if (Date.now() - inicio < Math.max(ESPERA_INICIAL_MS, TEMPO_MINIMO_MS)) return false
      if (pendentesAgora() > herdadas) {
        quietoDesde = null
        return false
      }
      if (quietoDesde === null) {
        quietoDesde = Date.now()
        return false
      }
      return Date.now() - quietoDesde >= SILENCIO_MS
    }

    rodando.current = true
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
      rodando.current = false
      limpar()
      window.clearTimeout(saida)
    }
  }, [pathname, gatilhoManual])

  if (!visivel) return null

  return (
    <div
      className="fixed inset-x-0 top-0 z-[100] h-[3px] pointer-events-none"
      /* Marca estável pra varredura visual medir quando a barra entra e sai ·
         a classe utilitária muda com o design, o papel não. */
      data-barra-topo=""
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
