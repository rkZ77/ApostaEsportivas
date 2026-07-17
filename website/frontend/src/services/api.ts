import axios from 'axios'
import { notifyError } from './errorToast'

// withCredentials envia/recebe cookies httpOnly automaticamente
const api = axios.create({ baseURL: '/api', withCredentials: true, timeout: 15000 })

let _refreshing: Promise<unknown> | null = null

// Sessão deslizante: renova o access token silenciosamente via refresh cookie.
// O refresh token dura 7 dias a partir do login e NÃO é renovado · após 7 dias, precisa logar de novo.
api.interceptors.response.use(
  (res) => res,
  async (err) => {
    const original = err.config
    // Never retry auth endpoints · surface errors directly to the caller
    if (original.url?.includes('/auth/')) {
      return Promise.reject(err)
    }
    if (err.response?.status === 401 && !original._retry) {
      original._retry = true

      // Sessão invalidada por novo login em outro dispositivo
      const detail: string = err.response?.data?.detail ?? ''
      if (detail.startsWith('SESSION_INVALIDATED|')) {
        const device = detail.split('|')[1] ?? 'outro dispositivo'
        localStorage.setItem('session_kicked_device', device)
        localStorage.removeItem('user')
        window.location.href = '/login?kicked=1'
        return Promise.reject(err)
      }

      if (!_refreshing) {
        _refreshing = api.post('/auth/refresh')
          .catch(() => {
            localStorage.removeItem('user')
            const path = window.location.pathname
            if (path !== '/login' && path !== '/') window.location.href = '/login'
          })
          .finally(() => { _refreshing = null })
      }
      await _refreshing
      return api(original)
    }

    // Falhas de rede/timeout e erros 5xx muitas vezes são engolidos por
    // `.catch(() => {})` nas telas (polling em background, stats opcionais).
    // Sem isso o usuário não sabia que algo falhou.
    if (!err.response) {
      notifyError('Sem conexão com o servidor. Verifique sua internet.')
    } else if (err.response.status >= 500) {
      notifyError('Erro no servidor. Tente novamente em instantes.')
    }
    return Promise.reject(err)
  }
)

export default api
