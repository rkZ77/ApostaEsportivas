import { useEffect, useRef, useState } from 'react'
import { assinarPendentes, pendentesAgora } from '../services/progressBus'
import { encerrarBarraInicial } from '../lib/barraInicial'

/*
 * Portão de revelação: a tela aparece INTEIRA, de uma vez.
 *
 * O PROBLEMA
 * ----------
 * Cada página do app busca seus dados em três, quatro, às vezes seis chamadas
 * independentes, e cada bloco trocava o próprio spinner pelo próprio conteúdo
 * assim que a SUA resposta chegava. Do lado de quem usa, a tela se montava em
 * etapas, na ordem em que o servidor respondesse, com a altura mudando embaixo
 * do dedo · no celular isso é o bastante para o toque acertar outra coisa.
 *
 * Um site que mostra tudo 400ms depois é percebido como mais rápido que um que
 * começa a mostrar em 150ms e só termina em 900ms. É o mesmo tempo total, mas
 * um tem um único instante de espera e o outro tem quatro. A espera única é
 * coberta pela barra verde do topo, que é a mesma em todas as telas.
 *
 * COMO ELE SABE QUE A TELA TERMINOU
 * ---------------------------------
 * Pelo contador de requisições em voo do progressBus, o mesmo que a barra do
 * topo lê. Nenhuma página precisa declarar "meu loading é esta variável": quem
 * monta, pede; quando ninguém mais está pedindo, está pronto.
 *
 * QUEM USA ISTO NÃO PODE DESMONTAR OS FILHOS
 * ------------------------------------------
 * O conteúdo fica montado o tempo todo, só invisível (opacidade). Não é
 * detalhe: é a montagem dele que dispara as chamadas que este portão espera.
 * Renderizar nada enquanto carrega faria o contador nunca sair de zero, e a
 * tela abriria vazia no primeiro quadro. Manter montado também reserva a
 * altura, então a revelação não empurra a página.
 *
 * REVELA UMA VEZ SÓ
 * -----------------
 * Depois de aberto, nunca mais fecha. Metade das telas do site faz polling
 * (LivePicks, o sino, o Admin de 3 em 3 segundos) · um portão que reagisse ao
 * contador para sempre apagaria a tela sozinho a cada ciclo de atualização.
 */

/** Janela pra tela disparar as chamadas dela antes de olharmos o contador ·
 *  no instante da montagem ainda não há nada em voo, e sem isto todo portão
 *  abriria no primeiro quadro, vazio. */
const GRACA_MS = 140
/** Teto absoluto. Endpoint lento ou fora do ar não pode segurar a tela: passou
 *  disto, revela o que houver, inclusive os spinners internos da página. */
const TETO_MS = 2200

export const FADE_REVELACAO_MS = 220

/** @param desligado tela sem carga inicial (termos, privacidade) revela direto. */
export function useRevelacao(desligado = false): boolean {
  const [revelado, setRevelado] = useState(desligado)
  const jaRevelou = useRef(desligado)

  useEffect(() => {
    if (jaRevelou.current) { encerrarBarraInicial(); return }

    const inicio = Date.now()
    let desassinar: () => void = () => {}
    let vigia: number | undefined
    let limite: number | undefined

    const abrir = () => {
      if (jaRevelou.current) return
      jaRevelou.current = true
      desassinar()
      window.clearInterval(vigia)
      window.clearTimeout(limite)
      setRevelado(true)
      /* A barra do index.html cobre a espera até aqui · este é o primeiro
         instante em que existe tela de verdade para olhar. */
      encerrarBarraInicial()
    }

    const podeAbrir = () => Date.now() - inicio >= GRACA_MS && pendentesAgora() === 0

    /* Duas fontes pro mesmo fim: o contador avisa quando a última resposta
       chega, e o vigia cobre a tela que nunca chegou a pedir nada. */
    desassinar = assinarPendentes(() => { if (podeAbrir()) abrir() })
    vigia = window.setInterval(() => { if (podeAbrir()) abrir() }, 60)
    limite = window.setTimeout(abrir, TETO_MS)

    return () => {
      desassinar()
      window.clearInterval(vigia)
      window.clearTimeout(limite)
    }
  }, [])

  return revelado
}

/** Classes do portão. Opacidade, nunca `display` ou `visibility`: o conteúdo
 *  precisa continuar ocupando altura pra revelação não empurrar a página. */
export function classesRevelacao(revelado: boolean): string {
  return revelado
    ? 'opacity-100 transition-opacity ease-out motion-reduce:transition-none'
    : 'opacity-0 pointer-events-none transition-opacity ease-out motion-reduce:transition-none'
}
