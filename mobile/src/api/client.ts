/**
 * Cliente HTTP do app. Fala com o MESMO backend do site.
 *
 * Equivalente nativo de `website/frontend/src/services/api.ts`: mesma ideia
 * de sessão deslizante (401 -> refresh -> repete a requisição uma vez), com
 * duas diferenças que vêm do ambiente, não de regra de negócio:
 *
 *   1. credencial vai no header `Authorization`, não em cookie;
 *   2. o header `X-Client-Platform` identifica o app para o backend devolver
 *      os tokens no corpo (ver `_tokens_no_corpo` em routers/auth.py).
 *
 * Nenhuma regra de pick, EV, confiança ou VIP é decidida aqui. O app pede e
 * mostra; quem decide continua sendo o motor.
 */
import axios, { AxiosError, AxiosRequestConfig } from 'axios'
import { Platform } from 'react-native'
import { API_BASE_URL, TIMEOUT_MS } from '../config/env'
import { accessToken, limparSessao, refreshToken, salvarSessao } from './session'

/** Chamado quando a sessão morre de vez · a UI decide para onde mandar o usuário. */
let aoPerderSessao: ((motivo: 'expirada' | 'derrubada', dispositivo?: string) => void) | null = null

export function registrarPerdaDeSessao(fn: typeof aoPerderSessao) {
  aoPerderSessao = fn
}

const api = axios.create({
  baseURL: `${API_BASE_URL}/api`,
  timeout: TIMEOUT_MS,
  headers: { 'X-Client-Platform': Platform.OS === 'ios' ? 'ios' : 'android' },
})

api.interceptors.request.use((config) => {
  const token = accessToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

/* Mesma lógica do site: endpoints onde 401 significa "credencial errada" ou
   onde tentar refresh criaria recursão. */
const SEM_RETRY = ['/auth/login', '/auth/register', '/auth/refresh', '/auth/forgot-password', '/auth/reset-password']

/* Um refresh por vez. Sem isso, abrir uma tela que dispara cinco chamadas
   com o token vencido renderia cinco refreshes concorrentes. */
let refrescando: Promise<string | null> | null = null

async function renovarAccessToken(): Promise<string | null> {
  const refresh = refreshToken()
  if (!refresh) return null
  try {
    const { data } = await axios.post(
      `${API_BASE_URL}/api/auth/refresh`,
      {},
      {
        timeout: TIMEOUT_MS,
        headers: {
          Authorization: `Bearer ${refresh}`,
          'X-Client-Platform': Platform.OS === 'ios' ? 'ios' : 'android',
        },
      },
    )
    const novo: string | undefined = data?.access_token
    if (!novo) return null
    await salvarSessao(novo)
    return novo
  } catch {
    return null
  }
}

api.interceptors.response.use(
  (res) => res,
  async (erro: AxiosError<{ detail?: string }>) => {
    const original = erro.config as (AxiosRequestConfig & { _retry?: boolean }) | undefined
    const status = erro.response?.status

    if (!original || status !== 401 || SEM_RETRY.some((p) => original.url?.includes(p))) {
      return Promise.reject(erro)
    }

    // Sessão única: login em outro aparelho derruba esta. Não adianta
    // renovar -- o refresh carrega o mesmo session_id já invalidado.
    const detalhe = erro.response?.data?.detail ?? ''
    if (typeof detalhe === 'string' && detalhe.startsWith('SESSION_INVALIDATED|')) {
      await limparSessao()
      aoPerderSessao?.('derrubada', detalhe.split('|')[1] || undefined)
      return Promise.reject(erro)
    }

    if (original._retry) return Promise.reject(erro)
    original._retry = true

    if (!refrescando) {
      refrescando = renovarAccessToken().finally(() => {
        refrescando = null
      })
    }
    const novo = await refrescando

    if (!novo) {
      await limparSessao()
      aoPerderSessao?.('expirada')
      return Promise.reject(erro)
    }

    original.headers = { ...original.headers, Authorization: `Bearer ${novo}` }
    return api(original)
  },
)

/** Mensagem de erro pronta para a tela, já em português. */
export function mensagemDeErro(erro: unknown, padrao = 'Não foi possível carregar. Tente de novo.'): string {
  const e = erro as AxiosError<{ detail?: string }>
  if (e?.response?.data?.detail && typeof e.response.data.detail === 'string') {
    return e.response.data.detail
  }
  if (!e?.response) return 'Sem conexão com o servidor. Verifique sua internet.'
  if ((e.response.status ?? 0) >= 500) return 'Erro no servidor. Tente novamente em instantes.'
  return padrao
}

export default api
