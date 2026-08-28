export const CONTACT_URL = import.meta.env.VITE_CONTACT_URL ?? '#contato'
export const SITE_NAME   = 'Pick IA'
export const TURNSTILE_SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY ?? ''

/**
 * Aba "Picks Ao Vivo" visível para o assinante.
 *
 * LIGADA POR PADRÃO desde 2026-08-27 · o produto abriu.
 *
 * O padrão inverteu, e a inversão é a decisão. Enquanto o Motor Live estava em
 * validação, o padrão era desligado porque esquecer a variável só custava uma
 * aba escondida. Agora custa o contrário: esquecer a variável em produção
 * ESCONDERIA um produto que já existe, e ninguém perceberia · o site não
 * reclama de uma aba que não aparece.
 *
 * É a mesma escolha de `SIDE_EFFECTS` em runtime_env.py e de `STATS_SWEEP` na
 * varredura: o default é o comportamento certo, e a variável existe para
 * DESLIGAR quando algo dá errado, sem deploy de código:
 *
 *     VITE_LIVE_PICKS_ENABLED=false
 *
 * A aba continua sendo `premiumOnly` · "todos" aqui é todo assinante, e quem
 * não é vê o mesmo cadeado dos outros produtos VIP. E esconder a aba nunca foi
 * o que protege o dado: quem decide é `require_live_reader` no backend.
 */
export const LIVE_PICKS_ENABLED =
  (import.meta.env.VITE_LIVE_PICKS_ENABLED ?? 'true').toString().toLowerCase() !== 'false'
