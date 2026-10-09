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
  /* Desde 07/10 · só jogo todo (o provedor não publica o 1º tempo deles).
     `defesas_pro` = o goleiro DESTE time defendeu. */
  chutes_pro?: number | null; chutes_contra?: number | null
  impedimentos_pro?: number | null; impedimentos_contra?: number | null
  defesas_pro?: number | null; defesas_contra?: number | null
  posse: number | null
  /* 1º tempo · null em jogo sem a folha do 1º tempo (coletada desde 27/09). */
  gols_pro_1t?: number | null; gols_contra_1t?: number | null
  escanteios_pro_1t?: number | null; escanteios_contra_1t?: number | null
  amarelos_pro_1t?: number | null; amarelos_contra_1t?: number | null
  chutes_alvo_pro_1t?: number | null; chutes_alvo_contra_1t?: number | null
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
    /** [casa, fora] do jogo encerrado (match_statistics); null antes do fim. */
    placar_final?: [number, number] | null
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
export type Periodo = 'total' | '1t' | '2t'
/** Do ponto de vista de um time: o que ele FAZ, o que ele CEDE, ou o jogo todo. */
export type Quem = 'pro' | 'contra' | 'jogo'

export const ROTULO_PERIODO: Record<Periodo, string> = { total: 'Jogo todo', '1t': '1º tempo', '2t': '2º tempo' }

type Contador = 'gols' | 'escanteios' | 'amarelos' | 'chutes_alvo' | 'faltas'
  | 'chutes' | 'impedimentos' | 'defesas'

/**
 * O número de um jogo: de quem (pro/contra/jogo) e em que tempo.
 *
 * 2º tempo é total − 1º, e só existe quando os dois existem. Faltas não têm
 * 1º tempo no provedor, então fora do "jogo todo" o valor é null (a tela
 * desliga os tempos nesse mercado, e o null aqui é só a garantia).
 */
export function numero(j: JogoDoTime, c: Contador, quem: Quem, periodo: Periodo): number | null {
  const lado = (q: 'pro' | 'contra'): number | null => {
    const total = (j[`${c}_${q}` as keyof JogoDoTime] ?? null) as number | null
    if (periodo === 'total') return total
    const prim = (j[`${c}_${q}_1t` as keyof JogoDoTime] ?? null) as number | null
    if (periodo === '1t') return prim
    return total == null || prim == null ? null : total - prim
  }
  if (quem !== 'jogo') return lado(quem)
  const a = lado('pro'), b = lado('contra')
  return a == null || b == null ? null : a + b
}

export interface MercadoDeTime {
  id: string
  /** Rótulo curto, para o chip. */
  rotulo: string
  /** Como a seleção se lê no bilhete: "Escanteios no jogo". */
  frase: string
  contador: Contador
  /** 'jogo' soma os dois times; 'time' é de um time só (faz x cede). */
  escopo: 'jogo' | 'time'
  linhaPadrao: number
  /** Linha padrão quando o recorte é um tempo só (metade do jogo, mais ou menos). */
  linhaPadraoTempo: number
  /** Faltas só existem no jogo todo. */
  soTotal?: boolean
}

export const MERCADOS_DE_TIME: MercadoDeTime[] = [
  { id: 'gols', rotulo: 'Gols', frase: 'Gols no jogo', contador: 'gols', escopo: 'jogo', linhaPadrao: 2.5, linhaPadraoTempo: 0.5 },
  { id: 'escanteios', rotulo: 'Escanteios', frase: 'Escanteios no jogo', contador: 'escanteios', escopo: 'jogo', linhaPadrao: 9.5, linhaPadraoTempo: 4.5 },
  { id: 'cartoes', rotulo: 'Cartões', frase: 'Cartões amarelos no jogo', contador: 'amarelos', escopo: 'jogo', linhaPadrao: 4.5, linhaPadraoTempo: 1.5 },
  { id: 'chutes_alvo', rotulo: 'Chutes no alvo', frase: 'Chutes no alvo no jogo', contador: 'chutes_alvo', escopo: 'jogo', linhaPadrao: 8.5, linhaPadraoTempo: 3.5 },
  { id: 'faltas', rotulo: 'Faltas', frase: 'Faltas no jogo', contador: 'faltas', escopo: 'jogo', linhaPadrao: 22.5, linhaPadraoTempo: 22.5, soTotal: true },
  { id: 'gols_time', rotulo: 'Gols do time', frase: 'Gols', contador: 'gols', escopo: 'time', linhaPadrao: 0.5, linhaPadraoTempo: 0.5 },
  { id: 'escanteios_time', rotulo: 'Escanteios do time', frase: 'Escanteios', contador: 'escanteios', escopo: 'time', linhaPadrao: 4.5, linhaPadraoTempo: 2.5 },
  { id: 'cartoes_time', rotulo: 'Cartões do time', frase: 'Cartões', contador: 'amarelos', escopo: 'time', linhaPadrao: 1.5, linhaPadraoTempo: 0.5 },
  { id: 'chutes_alvo_time', rotulo: 'Chutes no alvo do time', frase: 'Chutes no alvo', contador: 'chutes_alvo', escopo: 'time', linhaPadrao: 3.5, linhaPadraoTempo: 1.5 },
  { id: 'faltas_time', rotulo: 'Faltas do time', frase: 'Faltas', contador: 'faltas', escopo: 'time', linhaPadrao: 11.5, linhaPadraoTempo: 11.5, soTotal: true },
  /* 07/10/2026, pedido do usuário. Só jogo todo, como faltas. */
  { id: 'chutes', rotulo: 'Chutes', frase: 'Chutes no jogo', contador: 'chutes', escopo: 'jogo', linhaPadrao: 22.5, linhaPadraoTempo: 22.5, soTotal: true },
  { id: 'chutes_time', rotulo: 'Chutes do time', frase: 'Chutes', contador: 'chutes', escopo: 'time', linhaPadrao: 10.5, linhaPadraoTempo: 10.5, soTotal: true },
  { id: 'impedimentos', rotulo: 'Impedimentos', frase: 'Impedimentos no jogo', contador: 'impedimentos', escopo: 'jogo', linhaPadrao: 3.5, linhaPadraoTempo: 3.5, soTotal: true },
  { id: 'impedimentos_time', rotulo: 'Impedimentos do time', frase: 'Impedimentos', contador: 'impedimentos', escopo: 'time', linhaPadrao: 1.5, linhaPadraoTempo: 1.5, soTotal: true },
  { id: 'defesas', rotulo: 'Defesas do goleiro', frase: 'Defesas dos goleiros no jogo', contador: 'defesas', escopo: 'jogo', linhaPadrao: 5.5, linhaPadraoTempo: 5.5, soTotal: true },
  { id: 'defesas_time', rotulo: 'Defesas do goleiro do time', frase: 'Defesas do goleiro', contador: 'defesas', escopo: 'time', linhaPadrao: 2.5, linhaPadraoTempo: 2.5, soTotal: true },
]

/*
 * OS CINCO MERCADOS DA TELA (2026-10-07, pedido do usuário).
 *
 * Eram oito botões ("Gols", "Gols do time", "Escanteios do time"...), e a
 * fileira passava da tela. Agora são cinco, e dentro de cada um a pessoa
 * escolhe DE QUEM: os dois times somados, só o mandante ou só o visitante.
 * Cada par aponta pros dois mercados de cima: o "do jogo" e o "do time".
 */
export const MERCADOS_PRINCIPAIS: Array<{ id: string; rotulo: string; jogo: string; time: string }> = [
  { id: 'gols', rotulo: 'Gols', jogo: 'gols', time: 'gols_time' },
  { id: 'escanteios', rotulo: 'Escanteios', jogo: 'escanteios', time: 'escanteios_time' },
  { id: 'cartoes', rotulo: 'Cartões', jogo: 'cartoes', time: 'cartoes_time' },
  { id: 'chutes_alvo', rotulo: 'Chutes no alvo', jogo: 'chutes_alvo', time: 'chutes_alvo_time' },
  { id: 'faltas', rotulo: 'Faltas', jogo: 'faltas', time: 'faltas_time' },
  { id: 'chutes', rotulo: 'Chutes', jogo: 'chutes', time: 'chutes_time' },
  { id: 'impedimentos', rotulo: 'Impedimentos', jogo: 'impedimentos', time: 'impedimentos_time' },
  { id: 'defesas', rotulo: 'Defesas', jogo: 'defesas', time: 'defesas_time' },
]

/** "Escanteios no jogo · 1º tempo" · o tempo só entra no texto quando não é o jogo todo. */
export function comPeriodo(frase: string, periodo: Periodo): string {
  return periodo === 'total' ? frase : `${frase} · ${ROTULO_PERIODO[periodo]}`
}

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
    | 'faltas_sofridas' | 'desarmes' | 'defesas' | 'amarelos' | 'passes' | 'dribles'>
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
  /* 07/10 · já vinham na série do jogador, só não tinham botão. */
  { id: 'passes', rotulo: 'Passes', singular: 'passe', plural: 'passes', minimoPadrao: 30 },
  { id: 'dribles', rotulo: 'Dribles', singular: 'drible certo', plural: 'dribles certos', minimoPadrao: 1 },
]

/** "X ou mais" em cada jogo DO JOGADOR · a linha de prop é sempre mínimo. */
export function taxaDoJogador(j: Jogador, estat: EstatDeJogador['id'], minimo: number): Taxa {
  return taxa(j.jogos.map(g => g[estat]), minimo - 0.5, 'mais')
}

export function fraseDoJogador(estat: EstatDeJogador, minimo: number): string {
  return `${minimo}+ ${minimo === 1 ? estat.singular : estat.plural}`
}

export const ehGoleiro = (j: Jogador) => (j.posicao ?? '').toUpperCase().startsWith('G')

/* ── Casa / Fora (09/10/2026, pedido do usuário) ────────────────────────── */

/*
 * "RESPEITANDO O MANDANTE". Com 'mando', a amostra de cada time é só a do lado
 * em que ele joga ESTE jogo: o mandante nos jogos em casa, o visitante nos
 * jogos fora. É a leitura de quem diz "em casa ele é outro time".
 *
 * Jogador segue o time dele: fica só com os jogos que o time jogou daquele
 * lado. Jogo do jogador que não está na lista do time (mais antigo que ela)
 * sai também · sem saber o mando dele, contar seria chutar.
 */
export type Mando = 'todos' | 'mando'

export function filtrarPorMando(dados: RaioX, mando: Mando): RaioX {
  if (mando === 'todos') return dados
  const home = dados.times.home.jogos.filter(j => j.em_casa)
  const away = dados.times.away.jogos.filter(j => !j.em_casa)
  const doLado = (jogos: JogoDoTime[]) => new Set(jogos.map(j => j.fixture_id))
  const ladoHome = doLado(home)
  const ladoAway = doLado(away)
  const soDoLado = (lista: Jogador[], lado: Set<number>) =>
    lista.map(p => ({ ...p, jogos: p.jogos.filter(g => lado.has(g.fixture_id)) }))
  return {
    ...dados,
    times: {
      home: { ...dados.times.home, jogos: home },
      away: { ...dados.times.away, jogos: away },
    },
    jogadores: {
      home: { ...dados.jogadores.home, lista: soDoLado(dados.jogadores.home.lista, ladoHome) },
      away: { ...dados.jogadores.away, lista: soDoLado(dados.jogadores.away.lista, ladoAway) },
    },
  }
}

/* ── Forma ──────────────────────────────────────────────────────────────── */

export type Resultado = 'V' | 'E' | 'D'

export function resultadoDoJogo(j: JogoDoTime): Resultado | null {
  if (j.gols_pro == null || j.gols_contra == null) return null
  return j.gols_pro > j.gols_contra ? 'V' : j.gols_pro === j.gols_contra ? 'E' : 'D'
}

/*
 * Resultado final e chance dupla (2026-10-09, pedido do usuário).
 *
 * Mesma leitura de "faz x cede" dos mercados de time: "mandante vence" é o
 * mandante vencendo nos jogos dele E o visitante perdendo nos dele. Cada
 * escolha diz que resultado conta em cada lado.
 */
export type EscolhaDeResultado = '1' | 'X' | '2' | '1X' | '12' | 'X2'

export const RESULTADOS_ACEITOS: Record<EscolhaDeResultado, { home: Resultado[]; away: Resultado[] }> = {
  '1': { home: ['V'], away: ['D'] },
  X: { home: ['E'], away: ['E'] },
  '2': { home: ['D'], away: ['V'] },
  '1X': { home: ['V', 'E'], away: ['E', 'D'] },
  '12': { home: ['V', 'D'], away: ['V', 'D'] },
  X2: { home: ['E', 'D'], away: ['V', 'E'] },
}

/** 1 = o jogo terminou do jeito da escolha, 0 = não, null = sem placar. */
export function serieDeResultado(jogos: JogoDoTime[], aceitos: Resultado[]): Array<number | null> {
  return jogos.map(j => {
    const r = resultadoDoJogo(j)
    return r == null ? null : aceitos.includes(r) ? 1 : 0
  })
}

/** Cor do número de taxa: verde quando bate com folga, âmbar no meio. */
export function tomDaTaxa(pct: number | null): 'bom' | 'medio' | 'ruim' | 'nenhum' {
  if (pct == null) return 'nenhum'
  return pct >= 0.7 ? 'bom' : pct >= 0.5 ? 'medio' : 'ruim'
}
