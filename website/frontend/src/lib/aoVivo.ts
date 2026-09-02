/*
 * O que é "ao vivo", num vocabulário só.
 *
 * O MESMO status da API-Football era classificado de cinco jeitos diferentes
 * no site, e as divergências mudavam o que o usuário via:
 *
 *   arquivo                  ao vivo                        encerrado
 *   LivePicks.tsx            + SUSP, INT                    + CANC, PST, ABD, AWD, WO
 *   Fixtures.tsx             1H HT 2H ET BT P               FT AET PEN
 *   FixtureStatsModal.tsx    1H HT 2H ET BT P (inline)      FT AET PEN (inline)
 *
 * Um jogo SUSPENSO aparecia ao vivo em Minhas Apostas e como "nem ao vivo nem
 * encerrado" na Agenda. Um jogo CANCELADO contava como encerrado num lugar e
 * ficava em limbo no outro. Não é questão de gosto: é o mesmo jogo descrito de
 * duas formas em duas telas do mesmo produto.
 *
 * Os rótulos tinham o mesmo problema, e pior, porque aparecem escritos: o feed
 * de Picks Ao Vivo não conhecia CANC/PST/SUSP e mostrava o código cru --
 * "CANC" na tela, para o usuário.
 *
 * Aqui fica a régua. As telas escolhem só COMO desenhar -- mesma divisão de
 * `lib/periodo.ts`, que resolveu a mesma classe de problema entre Banca e Meus
 * Picks.
 */

/** Partida em andamento -- inclui intervalo, prorrogação e pênaltis.
 *
 * SUSP (suspenso) e INT (interrompido) entram: a partida NÃO acabou, e tratá-la
 * como encerrada apaga um jogo que ainda pode voltar a rolar. É a leitura que
 * Minhas Apostas já fazia, e é a correta -- as outras telas é que estavam
 * perdendo esses dois. */
export const AO_VIVO = new Set(['1H', 'HT', '2H', 'ET', 'BT', 'P', 'SUSP', 'INT'])

/** Partida que não vai mais produzir estatística -- por ter terminado ou por
 * ter sido cancelada. Os dois casos são iguais para quem exibe: não há mais
 * nada a acompanhar. Quem precisa distinguir "acabou" de "não aconteceu" usa
 * o rótulo, que nomeia cada um. */
export const ENCERRADO = new Set(
  ['FT', 'AET', 'PEN', 'CANC', 'PST', 'ABD', 'AWD', 'WO'])

export function aoVivo(status?: string | null): boolean {
  return !!status && AO_VIVO.has(status)
}

export function encerrado(status?: string | null): boolean {
  return !!status && ENCERRADO.has(status)
}

/** Rótulo em português de cada status. Cobre a lista inteira dos dois conjuntos
 * acima -- um status sem entrada aqui vira código cru na tela, que foi
 * exatamente o defeito do feed. */
export const STATUS_LABEL: Record<string, string> = {
  NS: 'Não iniciado',
  TBD: 'A definir',
  '1H': '1º Tempo',
  HT: 'Intervalo',
  '2H': '2º Tempo',
  ET: 'Prorrogação',
  BT: 'Intervalo da prorrogação',
  P: 'Pênaltis',
  SUSP: 'Suspenso',
  INT: 'Interrompido',
  FT: 'Encerrado',
  AET: 'Encerrado na prorrogação',
  PEN: 'Encerrado nos pênaltis',
  CANC: 'Cancelado',
  PST: 'Adiado',
  ABD: 'Abandonado',
  AWD: 'Decidido pela mesa',
  WO: 'W.O.',
}

/** Nunca devolve vazio: sem rótulo conhecido, o código cru é melhor que nada --
 * mas a lista acima existe pra isso não acontecer. */
export function rotuloDoStatus(status?: string | null): string {
  if (!status) return '-'
  return STATUS_LABEL[status] ?? status
}

/** Escudo do time, pelo proxy do backend. A URL estava copiada em quatro
 * arquivos; trocar o caminho exigia lembrar dos quatro. */
export const escudoDoTime = (id?: number): string | null =>
  id ? `/api/proxy/team/${id}.png` : null
