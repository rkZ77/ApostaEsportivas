/*
 * Contador de requisições em voo, alimentado pelos interceptors do axios
 * (services/api.ts) e lido pela TopProgressBar.
 *
 * POR QUE UM CONTADOR E NÃO UM EVENTO POR REQUISIÇÃO
 * --------------------------------------------------
 * A barra do topo não desenha uma vez por XHR. Várias telas do site fazem
 * polling em segundo plano · LivePicks, o sino de notificações, o Admin de 3
 * em 3 segundos, Fixtures de 30 em 30 · e uma barra por requisição ficaria
 * piscando sozinha o tempo todo, sem o usuário ter pedido nada.
 *
 * O que a barra usa daqui é só a resposta pra "a tela nova já terminou de
 * buscar o que precisava?", ou seja: o contador voltou a zero. Quem decide
 * quando começar é a navegação, não este módulo.
 */
type Ouvinte = (pendentes: number) => void

let pendentes = 0
const ouvintes = new Set<Ouvinte>()

function avisar() {
  for (const ouvinte of ouvintes) ouvinte(pendentes)
}

export function requisicaoIniciou() {
  pendentes += 1
  avisar()
}

/* Nunca desce de zero: uma requisição cancelada pode chamar o fim duas vezes,
   e um contador negativo travaria a barra pra sempre. */
export function requisicaoTerminou() {
  pendentes = Math.max(0, pendentes - 1)
  avisar()
}

export function pendentesAgora(): number {
  return pendentes
}

export function assinarPendentes(ouvinte: Ouvinte): () => void {
  ouvintes.add(ouvinte)
  return () => { ouvintes.delete(ouvinte) }
}

/*
 * Navegação que não troca de rota.
 *
 * As abas de /picks são estado, não rota (só leem o hash no deep link), então
 * a barra do topo não teria como percebê-las · e trocar de aba é uma espera
 * igualzinha às outras pra quem está usando. Quem provoca esse tipo de troca
 * avisa por aqui.
 */
type OuvinteNavegacao = () => void
const ouvintesNavegacao = new Set<OuvinteNavegacao>()

export function sinalizarNavegacao() {
  for (const ouvinte of ouvintesNavegacao) ouvinte()
}

export function assinarNavegacao(ouvinte: OuvinteNavegacao): () => void {
  ouvintesNavegacao.add(ouvinte)
  return () => { ouvintesNavegacao.delete(ouvinte) }
}
