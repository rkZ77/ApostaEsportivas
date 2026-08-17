/**
 * Eventos de funil no GA4.
 *
 * O QUE ESTE ARQUIVO **NÃO** FAZ: `purchase`. A receita é enviada pelo
 * servidor, de `_apply_approved_payment` (ver backend/analytics.py), e o
 * motivo está lá: quem paga por PIX fecha a aba na tela do MercadoPago e
 * nunca volta pro site, e bloqueador de anúncio é comum neste público. Medir
 * a venda daqui perderia dinheiro justamente nos canais que mais convertem.
 *
 * O que sobra pro navegador é o funil ANTES da venda · ver a página de
 * planos, iniciar o checkout, criar conta, entrar. Esses eventos só existem
 * do lado do cliente: o servidor não sabe que alguém olhou a tabela de
 * preços. São eles que preenchem a "Jornada de compra" e a atribuição de
 * canal no relatório.
 *
 * NADA DE DADO PESSOAL AQUI. Nome, e-mail, telefone e CPF não podem ir pro
 * GA · além de violar os termos de uso, dá pra derrubar a propriedade
 * inteira. O identificador de usuário é o id interno, e ele é enviado pelo
 * servidor, não daqui.
 */

const MOEDA = 'BRL'

type Parametros = Record<string, unknown>

/**
 * O mínimo de um plano que o GA precisa. Aceita o `Plan` de usePlans sem
 * conversão · o preço continua vindo de /api/payments/plans, que é a mesma
 * tabela que o MercadoPago cobra.
 */
export interface PlanoGA {
  id: string
  title?: string
  price: number
}

interface ItemGA {
  item_id: string
  item_name: string
  item_category: string
  price: number
  quantity: number
}

/**
 * Dispara um evento se o gtag estiver de pé.
 *
 * Silencioso de propósito quando não está: o script vem de fora e cai por
 * bloqueador com frequência neste público. Medição nunca pode derrubar, nem
 * atrasar, o fluxo de quem está comprando.
 */
function evento(nome: string, parametros: Parametros = {}): void {
  try {
    const gtag = (window as unknown as { gtag?: (...args: unknown[]) => void }).gtag
    if (typeof gtag !== 'function') return
    gtag('event', nome, parametros)
  } catch {
    /* medição não quebra tela */
  }
}

function paraItem(plano: PlanoGA): ItemGA {
  return {
    item_id: plano.id,
    item_name: plano.title || plano.id,
    item_category: 'assinatura',
    price: Number(plano.price) || 0,
    quantity: 1,
  }
}

/** Alguém abriu a tabela de preços. */
export function viuOsPlanos(planos: Array<PlanoGA>): void {
  if (!planos.length) return
  evento('view_item_list', {
    item_list_id: 'planos',
    item_list_name: 'Planos de assinatura',
    items: planos.map(paraItem),
  })
}

/** Alguém escolheu um plano e foi pro checkout. */
export function escolheuPlano(plano: PlanoGA): void {
  evento('select_item', { item_list_id: 'planos', items: [paraItem(plano)] })
}

/**
 * Último passo medido no navegador: o clique que cria o pagamento.
 *
 * Depois daqui o usuário sai do site pro MercadoPago, e o que acontece lá
 * só o servidor fica sabendo.
 */
export function iniciouCheckout(plano: PlanoGA): void {
  evento('begin_checkout', {
    currency: MOEDA,
    value: Number(plano.price) || 0,
    items: [paraItem(plano)],
  })
}

export function criouConta(): void {
  evento('sign_up', { method: 'email' })
}

export function entrou(): void {
  evento('login', { method: 'email' })
}
