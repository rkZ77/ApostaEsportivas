import axios from 'axios'

// withCredentials envia/recebe cookies httpOnly automaticamente
const api = axios.create({ baseURL: '/api', withCredentials: true })

// Sessão dura 8h. Quando o token expira (401), redireciona para login.
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      const path = window.location.pathname
      if (path !== '/login' && path !== '/') {
        localStorage.removeItem('user')
        window.location.href = '/login'
      }
    }
    return Promise.reject(err)
  }
)

export default api
