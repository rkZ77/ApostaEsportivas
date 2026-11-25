import { describe, expect, it, vi, afterEach } from 'vitest'
import api from './api'
import { subscribeError } from './errorToast'

/*
 * Retry de GET após 5xx / conexão cortada (deploy do container reiniciando).
 *
 * O ponto de partida é um caso real: a pessoa abriu /picks no segundo exato em
 * que um deploy novo reiniciou o backend, e a primeira carga ganhou um toast
 * vermelho "Erro no servidor" sem bug nenhum no código.
 */

type RespostaAxios = { data: unknown; status: number; statusText: string; headers: Record<string, string>; config: unknown; request: unknown }

const respostaOk = (cfg: unknown, data: unknown): RespostaAxios =>
  ({ data, status: 200, statusText: 'OK', headers: {}, config: cfg, request: null })

const erro5xx = (cfg: unknown, status: number) => {
  const err = new Error(`Request failed with status code ${status}`) as unknown as Record<string, unknown>
  err.isAxiosError = true
  err.config = cfg
  err.response = { data: {}, status, statusText: 'Erro', headers: {}, config: cfg, request: null }
  return err
}

/** Falha as N primeiras chamadas, depois responde. Conta as tentativas. */
function adapterQueFalha(vezesQueFalha: number, status = 500) {
  let chamadas = 0
  const adapter = async (cfg: unknown) => {
    chamadas++
    if (chamadas <= vezesQueFalha) throw erro5xx(cfg, status)
    return respostaOk(cfg, { ok: true })
  }
  return { adapter, tentativas: () => chamadas }
}

afterEach(() => {
  // O `api` é módulo único: devolve o adapter padrão pra não vazar pro resto.
  (api.defaults as Record<string, unknown>).adapter = undefined
})

describe('retry de GET em 5xx de deploy', () => {
  it(' tenta de novo sozinho e a chamada nem vê o erro', async () => {
    vi.useFakeTimers()
    const { adapter, tentativas } = adapterQueFalha(2)
    ;(api.defaults as Record<string, unknown>).adapter = adapter

    const p = api.get('/deploy-blip')
    // Duas esperas do interceptor: 0.8s e 2s.
    await vi.advanceTimersByTimeAsync(800)
    await vi.advanceTimersByTimeAsync(2000)
    const r = await p

    expect(r.data).toEqual({ ok: true })
    expect(tentativas()).toBe(3)   // a original + dois retries
    vi.useRealTimers()
  })

  it('não tenta POST de novo: 5xx em escrita falha na hora', async () => {
    vi.useFakeTimers()
    const { adapter, tentativas } = adapterQueFalha(1)
    ;(api.defaults as Record<string, unknown>).adapter = adapter

    const p = api.post('/escrita', { a: 1 }).catch((e: { response?: { status?: number } }) => {
      expect(e.response?.status).toBe(500)
      return null
    })
    await vi.advanceTimersByTimeAsync(3000)
    await p

    expect(tentativas()).toBe(1)   // nenhuma repetição
    vi.useRealTimers()
  })

  it('esgotados os retries, o erro segue pro chamador com o toast', async () => {
    vi.useFakeTimers()
    const { adapter, tentativas } = adapterQueFalha(9)
    ;(api.defaults as Record<string, unknown>).adapter = adapter

    const toasts: string[] = []
    const Sai = subscribeError(msg => toasts.push(msg))

    const p = api.get('/servidor-caido').catch(() => null)
    await vi.advanceTimersByTimeAsync(800)
    await vi.advanceTimersByTimeAsync(2000)
    await p

    expect(tentativas()).toBe(3)
    expect(toasts).toHaveLength(1)
    Sai()
    vi.useRealTimers()
  })

  it('não entra em retry quando o pedido foi cancelado', async () => {
    vi.useFakeTimers()
    let chamadas = 0
    ;(api.defaults as Record<string, unknown>).adapter = async (cfg: unknown) => {
      chamadas++
      const err = new Error('canceled') as unknown as Record<string, unknown>
      err.code = 'ERR_CANCELED'
      err.config = cfg
      throw err
    }

    const p = api.get('/navegou-pra-outro-lado').catch(() => null)
    await vi.advanceTimersByTimeAsync(3000)
    await p

    expect(chamadas).toBe(1)
    vi.useRealTimers()
  })
})
