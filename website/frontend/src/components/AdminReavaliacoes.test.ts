import { describe, expect, it } from 'vitest'
import { resumoDaReavaliacao, type Reavaliacao } from './AdminReavaliacoes'

const base: Reavaliacao = {
  pick_table: 'picks_vip', pick_id: 1, fixture_id: 9, reavaliado_em: '2026-10-08T15:30:00',
}

describe('resumoDaReavaliacao', () => {
  it('mostra o movimento da odd e do EV', () => {
    const r = resumoDaReavaliacao({ ...base, odd_publicada: '1.80', odd_agora: '1.62',
      prob_publicada: 0.62, prob_reavaliada: 0.62, ev_publicado: 0.116, ev_reavaliado: 0.0044 })
    expect(r).toContain('odd 1.8 → 1.62')
    expect(r).toContain('EV +11.6% → +0.4%')
    expect(r).not.toContain('prob')          // probabilidade nao mudou
    expect(r).toContain('antes do XI oficial')
  })
  it('conta os ausentes novos e a fração da produção', () => {
    const r = resumoDaReavaliacao({ ...base, odd_agora: 1.7, prob_publicada: 0.62,
      prob_reavaliada: 0.6, novos_ausentes: { home: [9, 10] }, fracao_perdida: 0.25,
      detalhe: { xi_oficial: true } })
    expect(r).toContain('prob 62.0% → 60.0%')
    expect(r).toContain('2 ausente(s) novo(s) · 25.0% da produção')
    expect(r).toContain('com XI oficial')
  })
  it('linha que sumiu do mercado', () => {
    expect(resumoDaReavaliacao({ ...base, odd_agora: null })).toContain('linha sem cotação agora')
  })
})
