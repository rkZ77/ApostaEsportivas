/*
 * O QUE É UM BILHETE DE VÁRIAS PERNAS, num lugar só.
 *
 * POR QUE ISTO EXISTE (10/09/2026, reclamação do usuário)
 * -------------------------------------------------------
 * O Bingo do Dia tem a mesma forma da Múltipla: pernas num JSONB `games`, odd
 * combinada, probabilidade combinada. O backend já trata os dois pelo MESMO
 * ramo (ver `routers/suggestions.py::detail` e `_TABELAS_CARTELA` em
 * `routers/banca.py`), mas a tela perguntava `pick_type === 'multipla'` solto,
 * em quatro arquivos diferentes, e o Bingo ficou de fora dos quatro:
 *
 *   SuggestionDetail  o painel não desenhava a lista de pernas, que é o
 *                     conteúdo inteiro do bilhete. Era o que o usuário via
 *                     como "o Bingo não funciona em Minhas Apostas".
 *   SuggestionCard    a stake sugerida saía de `calcVipStake` em vez de
 *                     `calcMultiplaStake` · a conta de pick simples num
 *                     bilhete de cinco pernas devolve unidade a mais.
 *   SuggestionCard    ao pegar o bilhete, ele ia consultar a odd de UMA
 *                     fixture, que num bilhete não existe.
 *   LivePicks         o acompanhamento ao vivo tratava o bilhete como pick de
 *                     um jogo só, inclusive no travamento antecipado.
 *
 * Comparação de string espalhada é o que faz um produto novo ser esquecido em
 * quatro lugares de uma vez, sem erro nenhum aparecer. A régua vira função, e
 * o próximo produto de bilhete entra aqui e em nenhum outro lugar.
 */

/** Bilhete de várias pernas com odd combinada: Múltipla e Bingo do Dia.
 *
 *  Alavancagem NÃO entra: ela é um caminho de degraus com régua própria (só
 *  vira dinheiro quando o caminho encerra), e os lugares que precisam tratar
 *  os três juntos dizem isso explicitamente. */
export function ehCartela(tipo: string | null | undefined): boolean {
  return tipo === 'multipla' || tipo === 'multiplas' || tipo === 'bingo'
}
