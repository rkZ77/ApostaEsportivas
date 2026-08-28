export const CONTACT_URL = import.meta.env.VITE_CONTACT_URL ?? '#contato'
export const SITE_NAME   = 'Pick IA'
export const TURNSTILE_SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY ?? ''

/**
 * Aba "Picks Ao Vivo" visível para o assinante · SEMPRE.
 *
 * Esta constante teve três vidas curtas: nasceu desligada (motor em validação),
 * virou "ligada salvo VITE_LIVE_PICKS_ENABLED=false" quando o produto abriu, e
 * em 2026-08-28 perdeu a variável — o usuário removeu as variáveis do Live no
 * Railway, e um interruptor que ninguém configura é só um caminho a mais para
 * o produto sumir por engano.
 *
 * Ela continua existindo como CONSTANTE, e não foi apagada, porque `Picks.tsx`
 * a usa para decidir a aba e o nome documenta a intenção ali. Se um dia o
 * produto precisar ser escondido de novo, é uma linha aqui — e uma linha que
 * aparece no diff, diferente de uma variável de ambiente que some sem rastro.
 *
 * A aba continua sendo `premiumOnly`: quem não é assinante vê o mesmo cadeado
 * dos outros produtos VIP. E quem decide o DADO é o backend.
 */
export const LIVE_PICKS_ENABLED = true
