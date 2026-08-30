import axios from 'axios'
import { notifyError } from './errorToast'
import { requisicaoIniciou, requisicaoTerminou } from './progressBus'

// withCredentials envia/recebe cookies httpOnly automaticamente
const api = axios.create({ baseURL: '/api', withCredentials: true, timeout: 15000 })

let _refreshing: Promise<unknown> | null = null

// Endpoints onde um 401 significa "credencial errada" (form) ou onde deixar
// passar pro fluxo de refresh criaria recursão (o próprio /auth/refresh) --
// esses nunca tentam refresh, só devolvem o erro pro chamador. Todo o resto,
// incluindo /auth/me, participa do refresh/kick normalmente: excluir /auth/me
// daqui fazia a checagem periódica de sessão (AuthContext) nunca perceber
// nem um token expirado nem uma sessão derrubada por login em outro
// dispositivo enquanto o usuário ficava parado numa tela sem outras chamadas.
// `/auth/google` entra na lista pelo mesmo motivo do login: um 401 ali é
// "este token do Google não vale", não "sua sessão expirou" · mandar isso pro
// fluxo de refresh só trocaria a mensagem de erro por um kick de sessão em
// quem nem estava logado.
const AUTH_NO_RETRY = ['/auth/login', '/auth/register', '/auth/google', '/auth/refresh', '/auth/forgot-password', '/auth/reset-password']

// Sessão deslizante: renova o access token silenciosamente via refresh cookie.
// O refresh token dura 7 dias a partir do login e NÃO é renovado · após 7 dias, precisa logar de novo.
/* Contagem de requisições em voo pra TopProgressBar saber quando a tela nova
   terminou de carregar. Só conta: nenhuma decisão de UI acontece aqui. O par
   incrementa/decrementa fecha em todos os caminhos, inclusive no retry após
   refresh · aquele reenvio passa por este mesmo interceptor e é contado como
   uma requisição nova, com o erro original já descontado. */
api.interceptors.request.use(
  (config) => { requisicaoIniciou(); return config },
  (error) => { requisicaoTerminou(); return Promise.reject(error) },
)

api.interceptors.response.use(
  (res) => { requisicaoTerminou(); return res },
  async (err) => {
    requisicaoTerminou()
    const original = err.config
    if (AUTH_NO_RETRY.some(p => original.url?.includes(p))) {
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
        const redirect = encodeURIComponent(window.location.pathname + window.location.search)
        window.location.href = `/login?kicked=1&redirect=${redirect}`
        return Promise.reject(err)
      }

      if (!_refreshing) {
        _refreshing = api.post('/auth/refresh')
          .catch(() => {
            localStorage.removeItem('user')
            const path = window.location.pathname
            if (path !== '/login' && path !== '/') {
              const redirect = encodeURIComponent(path + window.location.search)
              window.location.href = `/login?redirect=${redirect}`
            }
          })
          .finally(() => { _refreshing = null })
      }
      await _refreshing
      return api(original)
    }

    // Falhas de rede/timeout e erros 5xx muitas vezes são engolidos por
    // `.catch(() => {})` nas telas (polling em background, stats opcionais).
    // Sem isso o usuário não sabia que algo falhou.
    //
    // TRÊS CAUSAS DIFERENTES, TRÊS FRASES.
    //
    // "Verifique sua internet" era a única resposta para qualquer falha sem
    // `response`, e a mais comum delas não tem nada a ver com a internet de
    // quem lê: é o timeout de 15s daqui de cima estourando porque o servidor
    // demorou. Mandar o usuário conferir o wi-fi quando a fila é nossa faz ele
    // procurar defeito no lugar errado · e some com o único sinal de que o
    // site está devagar.
    if (!err.response) {
      const semRede = typeof navigator !== 'undefined' && navigator.onLine === false
      notifyError(
        semRede
          ? 'Você está sem internet. Reconecte e tente de novo.'
          : err.code === 'ECONNABORTED' || err.code === 'ETIMEDOUT'
          ? 'O servidor demorou para responder. Tente de novo em instantes.'
          : 'Não foi possível falar com o servidor. Tente de novo em instantes.'
      )
    } else if (err.response.status >= 500) {
      notifyError('Erro no servidor. Tente novamente em instantes.')
    }
    return Promise.reject(err)
  }
)

export default api
