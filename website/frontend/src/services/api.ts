import axios from 'axios'

// withCredentials envia/recebe cookies httpOnly automaticamente
const api = axios.create({ baseURL: '/api', withCredentials: true })

let _refreshing: Promise<unknown> | null = null

// Sessão deslizante: renova o access token silenciosamente via refresh cookie.
// O refresh token dura 7 dias a partir do login e NÃO é renovado — após 7 dias, precisa logar de novo.
api.interceptors.response.use(
  (res) => res,
  async (err) => {
    const original = err.config
    if (err.response?.status === 401 && !original._retry) {
      original._retry = true
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
    return Promise.reject(err)
  }
)

export default api
