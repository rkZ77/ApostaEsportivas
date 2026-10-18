/*
 * Endereço público de um jogo: /jogo/<fixture_id>/<casa>-x-<fora>.
 *
 * A MESMA regra de `slug_do_jogo` em backend/jogo_publico.py · o sitemap monta
 * a URL lá e a tela monta o link aqui. Se as duas divergirem, o Google indexa um
 * endereço e o site linka outro.
 *
 * O id é o que identifica o jogo; o slug existe pra a URL dizer do que se trata
 * (é o que aparece no resultado de busca). Slug errado ou velho não quebra nada:
 * a página corrige a barra de endereço pro canônico.
 */

function limpo(nome: string | null | undefined): string {
  return (nome ?? '')
    .normalize('NFKD')
    .replace(/[^\x00-\x7F]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

export function slugDoJogo(casa: string | null | undefined, fora: string | null | undefined): string {
  return `${limpo(casa) || 'casa'}-x-${limpo(fora) || 'fora'}`
}

export function caminhoDoJogo(j: { fixture_id: number; home_team?: string | null; away_team?: string | null }): string {
  return `/jogo/${j.fixture_id}/${slugDoJogo(j.home_team, j.away_team)}`
}
