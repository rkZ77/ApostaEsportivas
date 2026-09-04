/*
 * Recorte de período, num vocabulário só.
 *
 * Banca e Meus Picks leem o MESMO endpoint (/banca) e filtram a MESMA lista de
 * apostas, mas cada uma tinha a sua régua:
 *
 *   Banca      Tudo  | Hoje | 7 dias | 30 dias | Este mês | Mês passado
 *   Meus Picks Todos | Hoje | Semana |         | Este mês | Mês passado
 *
 * Três divergências no mesmo produto: "Tudo" contra "Todos", "7 dias" contra
 * "Semana", e um recorte de 30 dias que existia num lugar e não no outro. Quem
 * navega entre as duas telas lê isso como duas ferramentas diferentes, e
 * qualquer ajuste futuro precisava ser lembrado duas vezes.
 *
 * Aqui fica a lista e a conta. As telas escolhem só COMO desenhar.
 */

/* `mes:YYYY-MM` e' o recorte de um mes ESPECIFICO, escolhido numa lista
   suspensa (2026-09-04). Ele nao entra em PERIODOS: as pills sao janelas
   RELATIVAS a hoje ("7 dias", "Este mes"), e mes especifico e' outra pergunta
   -- "como foi agosto". Misturar os dois na mesma fila faria a fila crescer um
   item por mes, que foi o que tirou os meses das pills na pagina de Resultados.

   `Este mes` e `Mes passado` continuam nas pills: elas respondem sem exigir que
   o leitor saiba em que mes esta'. */
export type PeriodoKey = 'tudo' | 'hoje' | 'ontem' | '7d' | '30d' | 'mes' | 'mes_passado' | `mes:${string}`

export const PERIODOS: Array<{ key: PeriodoKey; label: string }> = [
  { key: 'tudo',        label: 'Tudo' },
  { key: 'hoje',        label: 'Hoje' },
  // "Ontem" é o recorte que mais se usa e o único que faltava: quase todo jogo
  // termina de madrugada, então na manhã seguinte "Hoje" está vazio e "7 dias"
  // mistura a rodada de ontem com a semana inteira. Sem ele, conferir a rodada
  // que acabou de fechar exigia contar no calendário.
  { key: 'ontem',       label: 'Ontem' },
  { key: '7d',          label: '7 dias' },
  { key: '30d',         label: '30 dias' },
  { key: 'mes',         label: 'Este mês' },
  { key: 'mes_passado', label: 'Mês passado' },
]

export const PERIODO_PADRAO: PeriodoKey = 'tudo'

/** "YYYY-MM-DD" de hoje em Brasília. en-CA é o locale que devolve nessa ordem. */
export function hojeBR(): string {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })
}

function diasAtrasBR(n: number): string {
  const d = new Date(`${hojeBR()}T12:00:00`)
  d.setDate(d.getDate() - n)
  return d.toLocaleDateString('en-CA')
}

/** Primeiro e último dia do mês, deslocado por `offset` (0 = atual, -1 = anterior). */
export function limitesDoMes(offset: number): { de: string; ate: string } {
  const hoje = hojeBR()
  const ano = Number(hoje.slice(0, 4))
  const mes = Number(hoje.slice(5, 7)) - 1 + offset
  const fmt = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  return { de: fmt(new Date(ano, mes, 1)), ate: fmt(new Date(ano, mes + 1, 0)) }
}

/**
 * Janela do período como par de datas, ou null para "tudo".
 *
 * Devolve data e não quantidade de dias porque é assim que os dois lados
 * consomem: a Banca manda `from_date`/`to_date` pro servidor e Meus Picks
 * compara em memória. Com "7 dias" solto, cada tela fazia a própria conta de
 * fuso e elas divergiam na virada da meia-noite.
 */
export function janelaDoPeriodo(p: PeriodoKey): { de: string; ate: string } | null {
  if (p === 'tudo') return null
  if (p === 'hoje') return { de: hojeBR(), ate: hojeBR() }
  // Janela fechada em ontem, não "de ontem até hoje": senão "Ontem" mostraria
  // os jogos de hoje junto e deixaria de responder o que ele pergunta.
  if (p === 'ontem') return { de: diasAtrasBR(1), ate: diasAtrasBR(1) }
  if (p === '7d')   return { de: diasAtrasBR(7),  ate: hojeBR() }
  if (p === '30d')  return { de: diasAtrasBR(30), ate: hojeBR() }
  return limitesDoMes(p === 'mes' ? 0 : -1)
}

/** true se a data "YYYY-MM-DD" cai dentro do período. */
export function dentroDoPeriodo(dia: string, p: PeriodoKey): boolean {
  // Mes especifico: comparacao de prefixo, sem construir Date. O dia ja' vem
  // como "YYYY-MM-DD" em Brasilia (ver hojeBR), entao os sete primeiros
  // caracteres SAO o mes -- e nenhuma conversao de fuso entra no meio.
  if (typeof p === 'string' && p.startsWith('mes:')) return dia.slice(0, 7) === p.slice(4)
  const j = janelaDoPeriodo(p)
  if (!j) return true
  return dia >= j.de && dia <= j.ate
}


/** "2026-09" -> "Setembro de 2026" (ou "set/26" com `curto`).
 *
 * Mora aqui, e nao em cada tela, porque agora ha' DOIS leitores: a lista
 * suspensa de meses da pagina de Resultados e a de Meus Picks. Duas copias
 * escreveriam o mesmo mes de dois jeitos na primeira divergencia de formato.
 */
export function nomeDoMes(mes: string, curto = false): string {
  const [y, mo] = mes.split('-').map(Number)
  const texto = new Date(y, mo - 1).toLocaleDateString('pt-BR', curto
    ? { month: 'short', year: '2-digit' }
    : { month: 'long', year: 'numeric' })
  return texto.charAt(0).toUpperCase() + texto.slice(1)
}
