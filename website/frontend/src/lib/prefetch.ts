/*
 * Pré-carga dos chunks de rota.
 *
 * Toda página do site é `lazy()` (ver App.tsx), o que é certo: ninguém deve
 * baixar o Admin de 213 KB para ler os Termos. O preço disso é que a espera do
 * download passa a acontecer DEPOIS do clique · a pessoa toca em "Picks" e só
 * então o navegador vai buscar o arquivo.
 *
 * A correção é buscar antes do clique, nos dois únicos momentos em que isso é
 * de graça:
 *
 *   1. Quando o navegador está ocioso, logo após a tela atual terminar. Aí já
 *      se sabe qual é o próximo passo provável de quem está ali · quem entrou
 *      vai para /picks, quem não entrou vai para /planos ou /login.
 *   2. Quando o dedo/ponteiro encosta no link, uns 200ms antes do clique
 *      acontecer. Não parece muito e é: dá para baixar 25 KB nesse tempo.
 *
 * `import()` é memoizado pelo próprio navegador, então chamar de novo no clique
 * não baixa nada uma segunda vez · ou o arquivo já está lá, ou a promessa em
 * andamento é reaproveitada. Chamar à toa custa zero.
 *
 * Só ENTRA AQUI rota que a pessoa realmente pode abrir a seguir. Pré-carregar
 * tudo é o mesmo que não ter separado em chunks: gastaria a banda do celular
 * dela com telas que ela não vai ver.
 */

type Importador = () => Promise<unknown>

const ROTAS: Record<string, Importador> = {
  '/':            () => import('../pages/Home'),
  '/picks':       () => import('../pages/Picks'),
  '/planos':      () => import('../pages/Planos'),
  '/login':       () => import('../pages/Login'),
  '/banca':       () => import('../pages/Banca'),
  '/meus-picks':  () => import('../pages/MeusPicks'),
  '/resultados':  () => import('../pages/ResultadosPublicos'),
  '/estatisticas': () => import('../pages/Estatisticas'),
  '/fixtures':    () => import('../pages/Fixtures'),
  '/profile':     () => import('../pages/Profile'),
  '/checkout':    () => import('../pages/Checkout'),
  '/como-funciona': () => import('../pages/ComoFunciona'),
}

const jaPedidas = new Set<string>()

/** Normaliza `/banca/saque` → `/banca`: o mapa é por rota-raiz. */
function chave(destino: string): string | null {
  const limpo = destino.split('?')[0].split('#')[0]
  if (ROTAS[limpo]) return limpo
  const raiz = '/' + (limpo.split('/')[1] ?? '')
  return ROTAS[raiz] ? raiz : null
}

export function prefetchRota(destino: string) {
  const k = chave(destino)
  if (!k || jaPedidas.has(k)) return
  jaPedidas.add(k)
  /* Engolir a falha é proposital: isto é adiantamento, não carregamento. Se o
     chunk não vier agora, o clique tenta de novo pelo caminho normal e aí sim
     o erro tem para onde ir (RouteErrorBoundary). */
  ROTAS[k]().catch(() => { jaPedidas.delete(k) })
}

/*
 * Escuta única, no documento inteiro.
 *
 * A alternativa era pendurar `onPointerEnter` em cada link · e são links na
 * Navbar, na gaveta do celular, no SiteHeader, no Footer, nos CTAs da Home, nos
 * cards de plano. Cobrir todos à mão significa esquecer alguns hoje e esquecer
 * os próximos sempre. Como todo link do site vira um `<a href>` no fim (o
 * `<Link>` do router e o `<Button to=>` inclusive), um ouvinte no documento
 * pega os que existem e os que ainda vão existir.
 *
 * `pointerover` e não `pointerenter`: só o primeiro sobe na árvore, que é o que
 * permite ouvir de um lugar só.
 */
export function ouvirLinksParaPrefetch(): () => void {
  const aoTocar = (e: Event) => {
    const alvo = e.target as Element | null
    const link = alvo?.closest?.('a[href]') as HTMLAnchorElement | null
    if (!link) return
    /* Só link interno e comum: externo, download e "abrir em nova aba" não
       passam pelo router, então não existe chunk nenhum para adiantar. */
    if (link.target && link.target !== '_self') return
    if (link.hasAttribute('download')) return
    const href = link.getAttribute('href') || ''
    if (!href.startsWith('/')) return
    prefetchRota(href)
  }
  document.addEventListener('pointerover', aoTocar, { capture: true, passive: true })
  document.addEventListener('touchstart', aoTocar, { capture: true, passive: true })
  return () => {
    document.removeEventListener('pointerover', aoTocar, { capture: true })
    document.removeEventListener('touchstart', aoTocar, { capture: true })
  }
}

/**
 * Pré-carga ociosa do próximo passo provável.
 *
 * Roda uma vez por sessão, e só depois de a tela atual estar de pé: em conexão
 * ruim, disputar banda com a página que a pessoa está esperando agora deixaria
 * o site mais lento, não mais rápido, que é o oposto do objetivo.
 */
export function prefetchOcioso(logado: boolean) {
  const proximas = logado
    ? ['/picks', '/banca', '/meus-picks']
    : ['/planos', '/login', '/resultados']

  const rodar = () => proximas.forEach(prefetchRota)

  /* Conexão cara ou lenta não recebe adiantamento nenhum · aqui ele deixaria de
     ser economia de tempo e viraria consumo do plano de dados de quem não pediu. */
  const conexao = (navigator as unknown as {
    connection?: { saveData?: boolean; effectiveType?: string }
  }).connection
  if (conexao?.saveData) return
  if (conexao?.effectiveType && /2g/.test(conexao.effectiveType)) return

  const ocioso = (window as unknown as {
    requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number
  }).requestIdleCallback
  if (ocioso) ocioso(rodar, { timeout: 3000 })
  else window.setTimeout(rodar, 1500)
}
