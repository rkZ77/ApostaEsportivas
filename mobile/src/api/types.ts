/**
 * Formatos que o backend já devolve hoje. Nada aqui é inventado pelo app:
 * cada campo corresponde a uma coluna que o motor grava ou a um agregado que
 * o router calcula. Quando um campo é opcional, é porque o backend pode
 * mesmo devolver `null` (pick sem resultado, jogo sem odd registrada).
 */

export type Plano = 'free' | 'trial' | 'vip' | 'admin'

export interface Usuario {
  id: number
  name: string
  email: string
  phone?: string | null
  plan: Plano
  active: boolean
  expires_at?: string | null
  avatar_url?: string | null
  trial_used?: boolean
  email_verified?: boolean
}

/** GREEN/RED/PUSH/HALF-* saem do motor; `null` é pick ainda em aberto. */
export type Resultado = 'GREEN' | 'RED' | 'PUSH' | 'HALF-WIN' | 'HALF-LOSS' | 'VOID' | null

/** Pick pré-jogo · une o formato de picks_vip e picks_free, que diferem só no nome do campo de time. */
export interface Pick {
  id: number
  fixture_id?: number | null
  match_date?: string | null
  match_datetime?: string | null
  home_team_name?: string | null
  away_team_name?: string | null
  /** picks_free usa home_team/away_team em vez de *_name */
  home_team?: string | null
  away_team?: string | null
  home_team_id?: number | null
  away_team_id?: number | null
  league_id?: number | null
  league_name?: string | null
  market?: string | null
  market_type?: string | null
  line?: string | null
  odd?: number | null
  bet_house?: string | null
  confidence?: number | null
  probability?: number | null
  ev?: number | null
  edge?: number | null
  stake_pct?: number | null
  reasoning?: string | null
  result?: Resultado
  profit?: number | null
  is_followed?: boolean
  user_stake_units?: number | null
}

export interface RespostaHoje {
  dica_do_dia?: Pick | null
  vip?: Pick[]
  multiplas?: unknown[]
  alavancagem?: unknown | null
  faltas?: Pick[]
  goleiros?: Pick[]
}

/** Pick do Motor Live · campos extras de contexto da partida em andamento. */
export interface PickAoVivo extends Pick {
  minute_at_creation?: number | null
  home_goals_at_creation?: number | null
  away_goals_at_creation?: number | null
  remaining_minutes?: number | null
  stake_units?: number | null
  status?: string | null
  expiration_reason?: string | null
  odd_at_creation?: number | null
  segundos_de_validade?: number | null
  /** minuto/placar ao vivo, enriquecidos pelo backend a cada chamada */
  minute?: number | null
  home_goals?: number | null
  away_goals?: number | null
  stat_value?: number | null
  stat_label?: string | null
  direction?: string | null
  is_live?: boolean
  is_ft?: boolean
  pick_status?: string | null
  pick_type?: string
}

export interface FeedAoVivo {
  disponivel: boolean
  picks: PickAoVivo[]
  motivo?: string
  expirados_agora?: number
  liquidados_agora?: number
}

/** Uma aposta seguida pelo usuário · a linha de Minhas Apostas. */
export interface Aposta {
  id: number
  pick_id: number
  pick_type: string
  stake_units: number
  followed_at?: string | null
  home_team_name?: string | null
  away_team_name?: string | null
  home_team_id?: number | null
  away_team_id?: number | null
  market?: string | null
  line?: string | null
  odd?: number | null
  actual_odd?: number | null
  result: Resultado
  profit_units?: number | null
  pnl?: number | null
  bankroll_after?: number | null
}

export interface Banca {
  bankroll_start: number
  bankroll_current: number
  unit_value: number
  total_followed: number
  total_resolved: number
  greens: number
  reds: number
  push: number
  half_wins: number
  half_loss: number
  win_rate: number
  roi: number
  yield_roi: number
  total_pnl: number
  streak: number
  streak_type?: string | null
  best_streak?: number | null
  entries: Aposta[]
}

export interface ResumoDeHoje {
  vip: number
  free: number
  multiplas: number
  alavancagem: number
  faltas: number
  goleiros: number
  total: number
}
