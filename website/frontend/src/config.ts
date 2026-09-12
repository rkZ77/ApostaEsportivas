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

/**
 * Bingo do Dia · LIBERADO para todos os usuários em 12/09/2026.
 *
 * O produto passou 09/09 a 12/09 em teste com dado de PRODUÇÃO, visível só
 * para admin: medir em dev não servia, porque dev enxerga 8 ligas e produção
 * enxerga 14, então a cartela de lá não é a cartela que o assinante receberia.
 * A medição acabou e a flag virou.
 *
 * ISTO NÃO É O PAYWALL. Liberado quer dizer que o produto existe na tela para
 * quem não é admin: a aba aparece, a seção da aba Hoje aparece e o filtro de
 * Resultados oferece o Bingo. Quem não assina vê a aba com o mesmo cadeado dos
 * outros produtos VIP, e quem decide o DADO continua sendo o backend
 * (`website/backend/feature_flags.py::BINGO_BETA_ADMIN_ONLY`, o par desta
 * constante, com o mesmo nome de propósito, para não saírem de sincronia).
 *
 * PARA ESCONDER DE NOVO são duas linhas, e as duas aparecem no diff: esta e a
 * do `feature_flags.py`. Variável de ambiente já sumiu sem rastro uma vez
 * neste projeto (ver LIVE_PICKS_ENABLED acima).
 */
export const BINGO_BETA_ADMIN_ONLY = false

/** O Bingo aparece para ESTE usuário? `isAdmin` vem do useAuth(). */
export const bingoVisivel = (isAdmin: boolean) => !BINGO_BETA_ADMIN_ONLY || isAdmin

