import api from './api'

/*
 * O conteúdo do "Entenda esta análise", buscado UMA vez e guardado.
 *
 * O QUE ESTAVA ERRADO
 * -------------------
 * O modal abria e ia se montando sozinho: a forma do mercado chegava de uma
 * requisição, a amostra do motor de outra, cada uma com o próprio esqueleto e
 * cada uma terminando na hora dela. Quem abria via a tela pular duas vezes, e
 * o pior momento pra tela tremer é justamente o de ler número.
 *
 * AS DUAS COISAS QUE ISTO MUDA
 * ----------------------------
 * 1. UMA REQUISIÇÃO. O backend passou a responder as duas metades juntas
 *    (`/suggestions/<id>/analise`), então existe UM estado de carregamento em
 *    vez de dois competindo.
 *
 * 2. ANTES DE ABRIR. `prefetchAnalise` é chamado no primeiro sinal de que a
 *    pessoa vai clicar -- o dedo encostando no botão (`pointerdown`), que no
 *    celular acontece 100 a 300ms antes do clique, e o mouse chegando em cima
 *    no desktop. Nesse tempo a resposta costuma chegar, e o modal abre pronto.
 *
 * POR QUE UM CACHE DE PROMESSAS, E NÃO DE RESULTADOS
 * --------------------------------------------------
 * Porque o caso comum é o prefetch AINDA ESTAR NO AR quando o modal abre.
 * Guardando a promessa, o modal se pendura na mesma requisição em vez de
 * disparar a segunda; guardando só o resultado, cada abertura rápida viraria
 * duas chamadas iguais.
 *
 * O cache é por pick e vive enquanto a aba viver. Não há invalidação de
 * propósito: o que ele guarda é o retrato de uma análise que já aconteceu (a
 * amostra é gravada no instante da escolha, a forma do mercado é histórico
 * fechado), e reabrir o mesmo pick tem que ser instantâneo.
 */
export interface AnalisePick {
  market_form?: any
  amostra?: any
}

const cache = new Map<string, Promise<AnalisePick>>()

const chave = (pickId: number, pickType: string) => `${pickType}:${pickId}`

export function carregarAnalise(pickId: number, pickType: string): Promise<AnalisePick> {
  const k = chave(pickId, pickType)
  const guardado = cache.get(k)
  if (guardado) return guardado

  const promessa = api
    .get(`/suggestions/${pickId}/analise`, { params: { pick_type: pickType } })
    .then(r => (r.data ?? {}) as AnalisePick)
    .catch(err => {
      /* Falha não fica no cache: a próxima tentativa tem que poder dar certo.
         O modal renderiza sem os dois blocos, que é o mesmo que ele já fazia
         quando uma das duas rotas falhava. */
      cache.delete(k)
      throw err
    })

  cache.set(k, promessa)
  return promessa
}

/** Adianta a busca. Nunca levanta: é palpite sobre o que a pessoa vai fazer. */
export function prefetchAnalise(pickId?: number, pickType?: string): void {
  if (pickId == null || !pickType) return
  carregarAnalise(pickId, pickType).catch(() => {})
}
