/*
 * Raio-X do jogo · a conta por trás da aba Jogos (2026-10-06).
 *
 * O backend manda SÉRIES jogo a jogo (ver routers/fixtures.py:get_raio_x), e é
 * aqui que elas viram resposta para a pergunta de quem monta bilhete: "nos
 * últimos N jogos, quantas vezes isto bateu?". Ficar no cliente é o que deixa
 * a pessoa mexer na linha (9.5 → 10.5 escanteios, 1+ → 2+ chutes) e ver o
 * número mudar na hora, sem voltar ao servidor.
 *
 * Tudo aqui é função pura · testada em raioX.test.ts.
 */

export interface JogoDoTime {
  fixture_id: number
  data: string | null
  em_casa: boolean
  adversario_id: number
  adversario?: string
  gols_pro: number | null; gols_contra: number | null
  escanteios_pro: number | null; escanteios_contra: number | null
  amarelos_pro: number | null; amarelos_contra: number | null
  vermelhos_pro: number | null; vermelhos_contra: number | null
  chutes_alvo_pro: number | null; chutes_alvo_contra: number | null
  faltas_pro: number | null; faltas_contra: number | null
  posse: number | null
}

export interface JogoDoJogador {
  fixture_id: number
  minutos: number
  titular: boolean
  nota: number | null
  chutes: number | null; chutes_alvo: number | null; gols: number | null
  assistencias: number | null; faltas: number | null; faltas_sofridas: number | null
  desarmes: number | null; defesas: number | null; amarelos: number | null
  passes: number | null; dribles: number | null
}

export interface Jogador {
  player_id: number
  nome: string
  posicao: string | null
  titular_provavel: boolean
  minutos_total: number
  jogos: JogoDoJogador[]
}

export interface RaioX {
  fixture: {
    fixture_id: number; league_id: number | null
    home_team_id: number; away_team_id: number
    home_team: string; away_team: string
    match_datetime: string | null; status: string | null; round: string | null
  }
  times: { home: { team_id: number; jogos: JogoDoTime[] }; away: { team_id: number; jogos: JogoDoTime[] } }
  h2h: Array<{ data: string | null; home_team_id: number; away_team_id: number
               home_goals: number | null; away_goals: number | null
               escanteios: number | null; amarelos: number }>
  arbitro: { nome: string; jogos: Array<{ amarelos: number; vermelhos: number; faltas: number | null }> } | null
  jogadores: {
    home: { fonte_titulares: string; lista: Jogador[] }
    away: { fonte_titulares: string; lista: Jogador[] }
  }
}

/* ── Mercados de time ───────────────────────────────────────────────────── */

export type Lado = 'mais' | 'menos'

export interface MercadoDeTime {
  id: string
  /** Rótulo curto, para o chip. */
  rotulo: string
  /** Como a seleção se lê no bilhete: "Escanteios no jogo". */
  frase: string
  linhaPadrao: number
  passo: number
  /** O número daquele jogo, do ponto de vista do time; null = sem dado. */
  valor: (j: JogoDoTime) => number | null
}

const soma = (a: number | null, b: number | null) => (a == null || b == null ? null : a + b)

export const MERCADOS_DE_TIME: MercadoDeTime[] = [
  { id: 'gols', rotulo: 'Gols', frase: 'Gols no jogo', linhaPadrao: 2.5, passo: 1,
    valor: j => soma(j.gols_pro, j.gols_contra) },
  { id: 'escanteios', rotulo: 'Escanteios', frase: 'Escanteios no jogo', linhaPadrao: 9.5, passo: 1,
    valor: j => soma(j.escanteios_pro, j.escanteios_contra) },
  { id: 'cartoes', rotulo: 'Cartões', frase: 'Cartões amarelos no jogo', linhaPadrao: 4.5, passo: 1,
    valor: j => soma(j.amarelos_pro, j.amarelos_contra) },
  { id: 'chutes_alvo', rotulo: 'Chutes no alvo', frase: 'Chutes no alvo no jogo', linhaPadrao: 8.5, passo: 1,
    valor: j => soma(j.chutes_alvo_pro, j.chutes_alvo_contra) },
  { id: 'faltas', rotulo: 'Faltas', frase: 'Faltas no jogo', linhaPadrao: 22.5, passo: 1,
    valor: j => soma(j.faltas_pro, j.faltas_contra) },
  { id: 'gols_time', rotulo: 'Gols do time', frase: 'Gols do time', linhaPadrao: 0.5, passo: 1,
    valor: j => j.gols_pro },
  { id: 'escanteios_time', rotulo: 'Escanteios do time', frase: 'Escanteios do time', linhaPadrao: 4.5, passo: 1,
    valor: j => j.escanteios_pro },
  { id: 'cartoes_time', rotulo: 'Cartões do time', frase: 'Cartões do time', linhaPadrao: 1.5, passo: 1,
    valor: j => j.amarelos_pro },
]

/** Ambas marcam é sim/não, não linha · fica fora da régua de linha. */
export const ambasMarcam = (j: JogoDoTime): boolean | null =>
  j.gols_pro == null || j.gols_contra == null ? null : j.gols_pro > 0 && j.gols_contra > 0

/* ── A conta ────────────────────────────────────────────────────────────── */

export interface Taxa {
  /** Jogos em que bateu. */
  bateu: number
  /** Jogos com dado (os sem número não contam nem a favor nem contra). */
  n: number
  /** 0..1, ou null sem amostra. */
  pct: number | null
  media: number | null
}

/**
 * Quantas vezes `valores` passou da linha.
 *
 * Linha .5 nunca empata. Linha cheia (10.0) empata quando o valor é igual, e
 * empate é DEVOLUÇÃO na casa, não acerto nem erro: ele sai da amostra, que é
 * como a aposta trataria.
 */
export function taxa(valores: Array<number | null>, linha: number, lado: Lado): Taxa {
  const validos = valores.filter((v): v is number => v != null)
  const decididos = validos.filter(v => v !== linha)
  const bateu = decididos.filter(v => (lado === 'mais' ? v > linha : v < linha)).length
  const media = validos.length ? validos.reduce((a, b) => a + b, 0) / validos.length : null
  return {
    bateu,
    n: decididos.length,
    pct: decididos.length ? bateu / decididos.length : null,
    media,
  }
}

/** "Mais de 9.5" / "Menos de 2.5" · e linha inteira sem casa decimal à toa. */
export function rotuloDaLinha(linha: number, lado: Lado): string {
  const l = Number.isInteger(linha) ? String(linha) : linha.toFixed(1)
  return `${lado === 'mais' ? 'Mais' : 'Menos'} de ${l}`
}

/* ── Jogadores ──────────────────────────────────────────────────────────── */

export interface EstatDeJogador {
  id: keyof Pick<JogoDoJogador, 'chutes' | 'chutes_alvo' | 'gols' | 'assistencias' | 'faltas'
    | 'faltas_sofridas' | 'desarmes' | 'defesas' | 'amarelos'>
  rotulo: string
  /** "1+ chute no alvo", no singular e no plural. */
  singular: string
  plural: string
  minimoPadrao: number
  /** Só goleiro tem defesa; mostrar o zagueiro com 0 defesas é ruído. */
  soGoleiro?: boolean
}

export const ESTATS_DE_JOGADOR: EstatDeJogador[] = [
  { id: 'chutes_alvo', rotulo: 'No alvo', singular: 'chute no alvo', plural: 'chutes no alvo', minimoPadrao: 1 },
  { id: 'chutes', rotulo: 'Chutes', singular: 'chute', plural: 'chutes', minimoPadrao: 1 },
  { id: 'gols', rotulo: 'Gols', singular: 'gol', plural: 'gols', minimoPadrao: 1 },
  { id: 'assistencias', rotulo: 'Assist.', singular: 'assistência', plural: 'assistências', minimoPadrao: 1 },
  { id: 'faltas', rotulo: 'Faltas', singular: 'falta cometida', plural: 'faltas cometidas', minimoPadrao: 1 },
  { id: 'faltas_sofridas', rotulo: 'Sofridas', singular: 'falta sofrida', plural: 'faltas sofridas', minimoPadrao: 1 },
  { id: 'desarmes', rotulo: 'Desarmes', singular: 'desarme', plural: 'desarmes', minimoPadrao: 2 },
  { id: 'amarelos', rotulo: 'Cartão', singular: 'cartão', plural: 'cartões', minimoPadrao: 1 },
  { id: 'defesas', rotulo: 'Defesas', singular: 'defesa', plural: 'defesas', minimoPadrao: 3, soGoleiro: true },
]

/** "X ou mais" em cada jogo DO JOGADOR · a linha de prop é sempre mínimo. */
export function taxaDoJogador(j: Jogador, estat: EstatDeJogador['id'], minimo: number): Taxa {
  return taxa(j.jogos.map(g => g[estat]), minimo - 0.5, 'mais')
}

export function fraseDoJogador(estat: EstatDeJogador, minimo: number): string {
  return `${minimo}+ ${minimo === 1 ? estat.singular : estat.plural}`
}

export const ehGoleiro = (j: Jogador) => (j.posicao ?? '').toUpperCase().startsWith('G')

/* ── Forma ──────────────────────────────────────────────────────────────── */

export type Resultado = 'V' | 'E' | 'D'

export function resultadoDoJogo(j: JogoDoTime): Resultado | null {
  if (j.gols_pro == null || j.gols_contra == null) return null
  return j.gols_pro > j.gols_contra ? 'V' : j.gols_pro === j.gols_contra ? 'E' : 'D'
}

/** Cor do número de taxa: verde quando bate com folga, âmbar no meio. */
export function tomDaTaxa(pct: number | null): 'bom' | 'medio' | 'ruim' | 'nenhum' {
  if (pct == null) return 'nenhum'
  return pct >= 0.7 ? 'bom' : pct >= 0.5 ? 'medio' : 'ruim'
}
