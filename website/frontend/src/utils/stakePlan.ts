/**
 * Plano de stake do placar público, em unidades · ESPELHO de
 * backend/stake_plan.py.
 *
 * A fonte da verdade é o Python: é ele que multiplica `profit` e `stake` nas
 * consultas de /public/results e /suggestions/stats/quick. Este arquivo existe
 * porque o card de pick precisa do número ANTES de qualquer resposta do
 * backend · ele mostra "lucro do pick" para quem não apostou, e sem o plano
 * caía num 1u fixo que discordava do placar da mesma semana.
 *
 * Espelho não é segunda fonte: test_unidades_e_odd_2026_08.py lê os dois e
 * quebra se divergirem. Mudar aqui sem mudar lá (ou o contrário) não passa.
 *
 * ALAVANCAGEM VALE ZERO de propósito. Ela é um caminho, não um pick que se
 * liquida em unidade: só vira unidade na banca de quem apostou, quando o
 * caminho encerra (alavancagem_series). Zero aqui significa "não conta em
 * unidades" · quem exibe deve usar `contaEmUnidades` e escrever isso, nunca
 * estampar um `+0,0u` que parece defeito.
 */
export const STAKE_PADRAO: Record<string, number> = {
  vip:         4,
  free:        3,
  faltas:      3,
  goleiros:    3,
  multiplas:   1,
  // O front usa a forma de rota ('multipla'); o backend, o nome da tabela
  // ('multiplas'). As duas chaves apontam pro mesmo peso pra que nenhum
  // chamador precise normalizar antes de perguntar.
  multipla:    1,
  alavancagem: 0,
}

/** Fonte desconhecida entra com 1u: subestima, nunca infla. Igual ao Python. */
export const STAKE_FALLBACK = 1

/** Unidades do plano para um tipo de pick. */
export function stakeDe(pickType?: string | null): number {
  if (!pickType) return STAKE_FALLBACK
  const u = STAKE_PADRAO[pickType]
  return u === undefined ? STAKE_FALLBACK : u
}

/**
 * Se este tipo move o lucro em unidades do placar público.
 *
 * Quem lê o peso pra CALCULAR usa `stakeDe`; quem lê pra ESCREVER na tela
 * pergunta aqui. Espelha `conta_em_unidades` do backend.
 */
export function contaEmUnidades(pickType?: string | null): boolean {
  return stakeDe(pickType) > 0
}
