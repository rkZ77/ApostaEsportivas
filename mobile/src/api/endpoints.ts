/**
 * Todas as chamadas do app, num lugar só.
 *
 * Cada função aqui corresponde a um endpoint que JÁ EXISTE em
 * `website/backend/routers/`. Nenhum endpoint novo foi criado para o app, e
 * nenhuma regra é recalculada do lado do cliente: confiança, EV, stake e
 * resultado chegam prontos do motor.
 */
import api from './client'
import type { Aposta, Banca, FeedAoVivo, Pick, RespostaHoje, ResumoDeHoje, Usuario } from './types'

/* ── autenticação ─────────────────────────────────────────────────────── */

export interface RespostaLogin {
  user: Usuario
  access_token?: string
  refresh_token?: string
}

export const autenticacao = {
  entrar: (identifier: string, password: string) =>
    api.post<RespostaLogin>('/auth/login', { identifier, password }).then((r) => r.data),

  cadastrar: (dados: {
    name: string
    email: string
    password: string
    phone: string
    cpf: string
    username: string
    accepted_terms: boolean
  }) => api.post<RespostaLogin>('/auth/register', dados).then((r) => r.data),

  eu: () => api.get<Usuario>('/auth/me').then((r) => r.data),

  sair: () => api.post('/auth/logout').then((r) => r.data),

  esqueciSenha: (email: string) =>
    api.post('/auth/forgot-password', { email }).then((r) => r.data),
}

/* ── picks pré-jogo ───────────────────────────────────────────────────── */

export const picks = {
  /** Picks do dia · o backend já filtra por plano (VIP recebe tudo, free recebe a dica). */
  hoje: (data?: string) =>
    api.get<RespostaHoje>('/suggestions/today', { params: data ? { date: data } : undefined })
      .then((r) => r.data),

  /** `pick_type` decide de qual tabela o backend lê · default "vip", como no site. */
  detalhe: (id: number, tipo = 'vip') =>
    api.get<Pick>(`/suggestions/${id}/detail`, { params: { pick_type: tipo } }).then((r) => r.data),

  /** Picks gratuitos · visível também para quem não é VIP. */
  gratuitos: () => api.get<Pick[]>('/suggestions/picks-free').then((r) => r.data),

  historico: (params?: { limit?: number; offset?: number }) =>
    api.get('/suggestions/history', { params }).then((r) => r.data),

  resultadosRecentes: () => api.get('/suggestions/recent-results').then((r) => r.data),

  /** Segue o pick · alimenta Minhas Apostas. Mesma rota que o site usa. */
  seguir: (pick_id: number, pick_type: string, stake_units: number, actual_odd?: number | null) =>
    api.post('/banca/follow', { pick_id, pick_type, stake_units, actual_odd }).then((r) => r.data),

  deixarDeSeguir: (pick_id: number, pick_type: string) =>
    api.delete(`/banca/follow/${pick_id}/${pick_type}`).then((r) => r.data),
}

/* ── picks ao vivo ────────────────────────────────────────────────────── */

export const aoVivo = {
  /** Feed do Motor Live. Exige VIP no backend · um 403 aqui significa paywall, não erro. */
  feed: (limite = 30, incluirEncerrados = true) =>
    api.get<FeedAoVivo>('/live-picks/feed', {
      params: { limit: limite, incluir_encerrados: incluirEncerrados },
    }).then((r) => r.data),

  detalhe: (id: number) =>
    api.get(`/live-picks/${id}/detail`).then((r) => r.data),

  estatisticas: () => api.get('/live-picks/stats').then((r) => r.data),
}

/* ── minhas apostas ───────────────────────────────────────────────────── */

export const minhasApostas = {
  /** A banca completa: agregados + as apostas seguidas. Nada é recalculado no app. */
  carregar: (params?: { days?: number; resolved_limit?: number; resolved_offset?: number }) =>
    api.get<Banca>('/banca', { params }).then((r) => r.data),

  resumo: () => api.get('/banca/summary').then((r) => r.data),
}

export type { Aposta }

/* ── público ──────────────────────────────────────────────────────────── */

export const publico = {
  resumoDeHoje: () => api.get<ResumoDeHoje>('/public/today-summary').then((r) => r.data),

  resultados: (params?: { limit?: number }) =>
    api.get('/public/results', { params }).then((r) => r.data),

  pickCompartilhado: (tipo: string, id: number) =>
    api.get<Pick>(`/public/pick/${tipo}/${id}`).then((r) => r.data),
}

/* ── notificações ─────────────────────────────────────────────────────── */

export const notificacoes = {
  /** Central de notificações · o mesmo sino do site, já pronto para o app. */
  listar: () => api.get('/notifications').then((r) => r.data),

  marcarComoLida: (id: number) =>
    api.post(`/notifications/${id}/read`).then((r) => r.data),

  marcarTodasComoLidas: () => api.post('/notifications/read-all').then((r) => r.data),

  /*
   * Registro de push do aparelho NÃO entra aqui ainda, de propósito.
   * `POST /notifications/subscribe` espera uma inscrição Web Push
   * (endpoint + chaves p256dh/auth do Service Worker), que um app nativo não
   * produz -- ele tem um token Expo/FCM, formato diferente. Enfiar o token
   * nativo naquele endpoint corromperia a tabela que o site usa hoje.
   * O caminho certo é uma coluna/rota própria para token nativo, e isso é
   * mudança no sistema de notificações que está fora do escopo desta fase.
   * Ver src/push/registro.ts, que já obtém o token e o deixa pronto.
   */
}
