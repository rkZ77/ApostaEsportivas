/*
 * Encerramento da barra de carregamento inicial (a do index.html).
 *
 * Aquela barra é HTML e CSS puros de propósito: ela precisa estar andando antes
 * do primeiro byte de JavaScript rodar. O contrapeso é que ela não sabe sozinha
 * quando o site ficou pronto · quem sabe é o React, e é daqui que ele avisa.
 *
 * "Pronto" aqui não é "o bundle carregou", é "a primeira tela está montada COM
 * o conteúdo dela". Quem chama é o portão de revelação (components/Revelacao),
 * ou seja, o mesmo instante em que a página aparece inteira. Fechar antes disso
 * devolveria a barra para o vazio que ela existe para cobrir.
 */

/** Teto de segurança: tela que nunca revela não pode deixar a barra eterna. */
const TETO_MS = 12_000
/** Espera o fade do CSS antes de tirar o nó do documento. */
const SAIDA_MS = 500

let encerrada = false

export function encerrarBarraInicial() {
  if (encerrada || typeof document === 'undefined') return
  encerrada = true
  document.documentElement.classList.add('pronto')
  window.setTimeout(() => {
    document.getElementById('barra-inicial')?.remove()
  }, SAIDA_MS)
}

/** Rede travada, erro de chunk, tela que nunca chama o portão: some assim mesmo. */
if (typeof window !== 'undefined') {
  window.setTimeout(encerrarBarraInicial, TETO_MS)
}
