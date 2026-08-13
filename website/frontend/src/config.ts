export const CONTACT_URL = import.meta.env.VITE_CONTACT_URL ?? '#contato'
export const SITE_NAME   = 'Pick IA'
export const TURNSTILE_SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY ?? ''

/**
 * Aba "Picks Ao Vivo" visível para o assinante.
 *
 * DESLIGADA POR PADRÃO, e o padrão é a decisão: o código do Motor Live sobe
 * junto com o resto porque vive na mesma branch, mas o produto ainda não
 * existe para o usuário. Sem esta flag, todo VIP passaria a ver uma aba que
 * mostra "Nenhuma oportunidade ao vivo agora" para sempre · o motor não roda
 * em produção (exige DB_ENV=dev e LIVE_ENGINE_ALLOW_RUN) e a tabela
 * `picks_live` nem existe lá.
 *
 * Ligar é uma variável no Railway, sem deploy de código:
 *
 *     VITE_LIVE_PICKS_ENABLED=true
 *
 * Esconder a aba é suficiente porque a execução já está travada no backend ·
 * isto aqui é sobre o que o assinante vê, não sobre o motor rodar.
 */
export const LIVE_PICKS_ENABLED =
  (import.meta.env.VITE_LIVE_PICKS_ENABLED ?? '').toString().toLowerCase() === 'true'
