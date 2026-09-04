/*
 * As respostas que o index.html já foi buscar antes de o React existir.
 *
 * O PROBLEMA. As quatro chamadas que desenham o topo da Home (dica do dia,
 * fila de jogos, indicadores e preço) só saíam quando o React terminava de
 * baixar, avaliar e montar · medido em 04/09, isso é ~1,2s depois do primeiro
 * byte, num aparelho de celular em 4G. O servidor ficava parado esperando o
 * navegador terminar de ler JavaScript para só então ser perguntado.
 *
 * O QUE MUDA. Um script de três linhas no <head> dispara os quatro `fetch`
 * assim que o HTML chega, e guarda as Promises em `window.__pickia_precarga`.
 * Quando o app monta, ele encontra as respostas prontas (ou já em voo) e não
 * pede de novo. O ganho é o tempo inteiro de download e avaliação do bundle.
 *
 * POR QUE ISTO NÃO VAZA CONTEÚDO DE OUTRA SESSÃO. A autenticação é cookie
 * httpOnly (`withCredentials` no services/api.ts), e o fetch do HTML usa
 * `credentials: 'include'` · o servidor vê exatamente a mesma sessão que o
 * axios veria, então a resposta é a mesma que aquela requisição traria. O que
 * não bate (401, 500, rede caída) é DESCARTADO aqui e a chamada normal
 * acontece como se nada tivesse sido pré-carregado.
 *
 * CADA ENTRADA SÓ SERVE UMA VEZ. Depois disso o dado é velho, e quem pede de
 * novo (uma paginação, um refetch depois de agir na tela) tem que falar com o
 * servidor. Ver `consumir`.
 */

/** O que o script do index.html deixa em `window`. */
type Precarga = Record<string, Promise<unknown> | undefined>

function mapa(): Precarga | null {
  const w = window as unknown as { __pickia_precarga?: Precarga }
  return w.__pickia_precarga ?? null
}

/**
 * Chave da pré-carga: o caminho com os parâmetros na MESMA ordem do
 * index.html. Não é a URL do axios (que monta a query sozinho) porque as duas
 * precisam casar exatamente, e um `?slim=1&recent_limit=1` invertido não
 * casaria com nada · a lista literal aqui é o contrato com o HTML.
 */
export function chaveDaPrecarga(url?: string, params?: Record<string, unknown>): string | null {
  if (!url) return null
  const caminho = url.replace(/^\/api/, '')

  if (caminho === '/public/free-pick-today' && !params) return '/api/public/free-pick-today'
  if (caminho === '/payments/plans' && !params) return '/api/payments/plans'
  if (caminho === '/public/next-fixtures' && params?.limit === 30 && Object.keys(params).length === 1) {
    return '/api/public/next-fixtures?limit=30'
  }
  if (caminho === '/public/results'
      && params?.recent_limit === 1 && params?.slim === 1 && Object.keys(params).length === 2) {
    return '/api/public/results?recent_limit=1&slim=1'
  }
  return null
}

/**
 * Consome a resposta pré-carregada de `chave`, ou `undefined` se não houver
 * (ou se ela falhou). Chamar duas vezes com a mesma chave devolve `undefined`
 * na segunda: pré-carga é para a PRIMEIRA pintura, não é cache.
 */
export async function consumir(chave: string): Promise<unknown | undefined> {
  const m = mapa()
  const pendente = m?.[chave]
  if (!m || !pendente) return undefined
  delete m[chave]
  try {
    return await pendente
  } catch {
    return undefined
  }
}
