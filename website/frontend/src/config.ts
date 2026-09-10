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
 * Bingo do Dia · em teste com dado de PRODUÇÃO, visível só para admin.
 *
 * O produto está INTEIRO no código (motor, liquidação, banca, placar) e agora
 * roda em `main`, contra o banco de produção · decisão do usuário em 10/09.
 * Medir em dev não servia: dev enxerga 8 ligas e produção enxerga 14, então a
 * cartela de lá não é a cartela que o assinante receberia.
 *
 * O QUE MUDOU EM 10/09: até aqui o Bingo era escondido por um booleano do
 * front que subia `false` para `main`. Com o motor publicando cartela em
 * produção, esconder no front deixou de bastar -- a resposta de
 * `/api/suggestions/today` traria a cartela inteira para qualquer assinante
 * que abrisse o DevTools. Então o corte de verdade passou a ser o do SERVIDOR
 * (`website/backend/feature_flags.py::BINGO_BETA_ADMIN_ONLY`), e esta
 * constante virou o par dele: mesmo nome, mesmo valor, e o front só deixa de
 * desenhar o que o servidor já não manda.
 *
 * PARA LIBERAR PARA TODO MUNDO são duas linhas, e as duas aparecem no diff:
 * esta e a do `feature_flags.py`. Variável de ambiente já sumiu sem rastro uma
 * vez neste projeto (ver LIVE_PICKS_ENABLED acima).
 *
 * Os lugares que `bingoVisivel` fecha: a aba na barra, a seção da aba Hoje e o
 * filtro de produto em Resultados. O /admin NÃO entra na lista: a página
 * inteira já é de admin, e é lá que o produto é gerado e medido durante o
 * teste.
 */
export const BINGO_BETA_ADMIN_ONLY = true

/** O Bingo aparece para ESTE usuário? `isAdmin` vem do useAuth(). */
export const bingoVisivel = (isAdmin: boolean) => !BINGO_BETA_ADMIN_ONLY || isAdmin

