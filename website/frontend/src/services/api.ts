import axios from 'axios'

// withCredentials envia/recebe cookies httpOnly automaticamente
const api = axios.create({ baseURL: '/api', withCredentials: true })

let _refreshing: Promise<void> | null = null

api.interceptors.response.use(
  (res) => res,
  async (err) => {
    const original = err.config
    if (err.response?.status === 401 && !original._retry) {
      original._retry = true
      // Tenta renovar o token via refresh cookie
      if (!_refreshing) {
        _refreshing = api.post('/auth/refresh').catch(() => {
          localStorage.removeItem('user')
          window.location.href = '/login'
        }).finally(() => { _refreshing = null })
      }
      await _refreshing
      return api(original)
    }
    return Promise.reject(err)
  }
)

export default api
