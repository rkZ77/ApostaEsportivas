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
  /* Primeira requisição de uma rajada nascida de um toque · ver
     `nasceuDeUmGesto` no fim deste arquivo. As seguintes da mesma rajada não
     reiniciam a barra, senão ela voltaria a 8% a cada resposta que chega. */
  if (pendentes === 1 && nasceuDeUmGesto()) sinalizarNavegacao()
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


/*
 * A BARRA COMO PADRÃO DE TUDO.
 *
 * Trocar de rota e trocar de aba já puxavam a barra. Faltava o resto do que uma
 * pessoa faz numa tela e espera: mudar filtro, virar página da lista, escolher
 * outro período, mandar um formulário. Cada um desses pontos precisaria de uma
 * chamada explícita a `sinalizarNavegacao()`, e a cada tela nova alguém
 * esqueceria de uma · foi o que aconteceu, e é por isso que a regra virou
 * automática.
 *
 * O CRITÉRIO É O GESTO, NÃO A REQUISIÇÃO.
 *
 * Uma barra por requisição é o erro óbvio aqui: metade das telas faz polling em
 * segundo plano (LivePicks, o sino, o Admin de 3 em 3 segundos, Fixtures de 30
 * em 30), e a barra ficaria piscando sozinha enquanto a pessoa lê a tela
 * parada, dizendo "estou carregando" sem ninguém ter pedido nada.
 *
 * Então o que liga a barra é: houve um toque ou uma tecla há pouco, E esta é a
 * primeira requisição em voo. Poll de timer não tem gesto antes dele e não
 * acende nada. O `pointerdown` chega antes do `click`, então a marca já está lá
 * quando o handler dispara a chamada.
 */
const JANELA_DO_GESTO_MS = 800
let ultimoGesto = 0

function nasceuDeUmGesto(): boolean {
  return Date.now() - ultimoGesto < JANELA_DO_GESTO_MS
}

if (typeof document !== 'undefined') {
  const marcar = () => { ultimoGesto = Date.now() }
  /* Captura: um handler que chama `stopPropagation` não pode esconder o gesto
     de nós · é justamente em componente com handler próprio que ele acontece. */
  document.addEventListener('pointerdown', marcar, { capture: true, passive: true })
  document.addEventListener('keydown', marcar, { capture: true, passive: true })
  document.addEventListener('submit', marcar, { capture: true, passive: true })
}
