// @vitest-environment jsdom
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AxiosAdapter } from 'axios'
import api from '../services/api'
import { bilheteDe, versaoDosDados } from './sincronia'

/*
 * O defeito que isto segura (06/10/2026): pegar o bilhete em /picks e, ao
 * navegar e voltar, o card dizer "Pegar bilhete" de novo até o F5. A garantia
 * mora no api.ts, então é por ele que o teste passa · nenhum card precisa
 * lembrar de nada.
 */

/* O "servidor": responde `status` a qualquer pedido, sem rede. */
const adapterOriginal = api.defaults.adapter
function servidor(status: number, data: unknown = {}) {
  const adapter: AxiosAdapter = async config => {
    const resposta = { data, status, statusText: '', headers: {}, config }
    if (status >= 400) {
      throw Object.assign(new Error(`HTTP ${status}`), { config, response: resposta, isAxiosError: true })
    }
    return resposta
  }
  api.defaults.adapter = adapter
}

beforeEach(() => servidor(200))
afterEach(() => { api.defaults.adapter = adapterOriginal; vi.useRealTimers() })

describe('registro de bilhetes', () => {
  it('POST /banca/follow que deu certo marca o bilhete com o que foi enviado', async () => {
    await api.post('/banca/follow', {
      pick_id: 77, pick_type: 'free', stake_units: 2, actual_odd: 1.8, bet_house: 'Betano',
    })
    expect(bilheteDe('free', 77)).toEqual({ stakeUnits: 2, actualOdd: 1.8, betHouse: 'Betano' })
  })

  it('POST que falhou não marca nada', async () => {
    servidor(400, { detail: 'banca sem saldo' })
    await expect(api.post('/banca/follow', { pick_id: 78, pick_type: 'vip' })).rejects.toBeTruthy()
    expect(bilheteDe('vip', 78)).toBeUndefined()
  })

  it('DELETE /banca/follow/<id>/<tipo> desmarca, e o desfeito vence a lista velha', async () => {
    await api.post('/banca/follow', { pick_id: 79, pick_type: 'vip', stake_units: 1 })
    await api.delete('/banca/follow/79/vip')
    expect(bilheteDe('vip', 79)).toBeNull()
  })

  it('multipla e multiplas são o mesmo bilhete', async () => {
    await api.post('/banca/follow', { pick_id: 80, pick_type: 'multipla', stake_units: 1 })
    expect(bilheteDe('multiplas', 80)).not.toBeUndefined()
  })
})

describe('versão dos dados', () => {
  /* As escritas dos testes de cima deixaram um aviso agendado no relógio REAL
     (a janela de 250 ms que junta rajadas). Ele precisa disparar antes de o
     relógio falso entrar, senão a primeira escrita daqui cai dentro dele. */
  beforeAll(() => new Promise(r => setTimeout(r, 300)))

  it('escrita que deu certo sobe a versão uma vez só, mesmo em rajada', async () => {
    vi.useFakeTimers()
    const antes = versaoDosDados()
    await api.put('/banca/unidade', { unit: 10 })
    await api.post('/banca/deposit', { value: 50 })
    vi.advanceTimersByTime(300)
    expect(versaoDosDados()).toBe(antes + 1)
  })

  it('escrita de bastidor (notificação lida) não sobe a versão', async () => {
    vi.useFakeTimers()
    const antes = versaoDosDados()
    await api.post('/notifications/12/read')
    vi.advanceTimersByTime(300)
    expect(versaoDosDados()).toBe(antes)
  })

  it('voltar pra aba depois de 60 s fora sobe a versão; troca rápida não', () => {
    vi.useFakeTimers()
    const visivel = (estado: 'visible' | 'hidden') => {
      Object.defineProperty(document, 'visibilityState', { value: estado, configurable: true })
      document.dispatchEvent(new Event('visibilitychange'))
    }
    const antes = versaoDosDados()
    visivel('hidden'); vi.advanceTimersByTime(5_000); visivel('visible')
    expect(versaoDosDados()).toBe(antes)
    visivel('hidden'); vi.advanceTimersByTime(61_000); visivel('visible')
    expect(versaoDosDados()).toBe(antes + 1)
  })
})
