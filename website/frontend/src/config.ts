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
 * Bingo do Dia visível no site.
 *
 * O produto está INTEIRO no código (motor, liquidação, banca, placar) e roda
 * em dev e noprod desde 08/09. Esta linha existe para que qualquer outro
 * commit possa ir para produção sem levar o Bingo junto, enquanto ele ainda
 * está sendo medido · decisão do usuário em 09/09.
 *
 * A REGRA É A DO ARQUIVO: `dev` e `noprod` sobem com `true`, e o que for para
 * `main` sobe com `false`. Quando o produto for aprovado, é uma linha só, e
 * ela aparece no diff · diferente de uma variável de ambiente, que já sumiu
 * sem rastro uma vez (ver LIVE_PICKS_ENABLED acima).
 *
 * ELA GOVERNA O FRONT, E SÓ. O backend continua ligado de propósito: em
 * produção a tabela `picks_bingo` está vazia (o motor é um comando manual e
 * nunca rodou lá), então toda consulta devolve nada e não há o que esconder.
 * Um segundo interruptor do lado do servidor seria um par para manter em
 * sincronia, e par fora de sincronia é como o produto some pela metade.
 *
 * Os quatro lugares onde o Bingo aparece e que esta constante fecha: a aba na
 * barra, a seção da aba Hoje, o filtro de produto em Resultados e o botão
 * "Gerar Bingo do Dia" no /admin · esse último é o que impede um clique
 * distraído de publicar uma cartela em produção.
 */
export const BINGO_ENABLED = true
