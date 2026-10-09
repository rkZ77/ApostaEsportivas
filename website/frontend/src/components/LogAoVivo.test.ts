import { describe, expect, it } from 'vitest'
import { classificarLinha, corDaMarca } from './LogAoVivo'

describe('classificarLinha', () => {
  it('reconhece o cabeçalho de etapa do Rodar Tudo', () => {
    const l = classificarLinha('─── [4/12] Gerando Picks Premium ────────────────────')
    expect(l).toEqual({ tipo: 'etapa', texto: 'Gerando Picks Premium', etapa: { n: 4, total: 12 } })
  })
  it('separa a marca do script e marca sucesso', () => {
    const l = classificarLinha('[VIP_ENGINE] 3 picks salvos.')
    expect(l.marca).toBe('VIP_ENGINE')
    expect(l.tipo).toBe('ok')
    expect(l.texto).toBe('3 picks salvos.')
  })
  it('stderr com traceback é erro; stderr comum é aviso', () => {
    expect(classificarLinha('! Traceback (most recent call last):').tipo).toBe('erro')
    expect(classificarLinha('! UserWarning: algo').tipo).toBe('aviso')
    expect(classificarLinha('! Etapa CANCELADA pelo admin').tipo).toBe('erro')
  })
  it('aviso de pick não publicado', () => {
    const l = classificarLinha('[VIP_ENGINE] Fixture 1: pick NAO publicado na revalidacao -- linha fora do ar')
    expect(l.tipo).toBe('aviso')
  })
  it('linha comum fica normal e o texto não muda', () => {
    expect(classificarLinha('[ODDS] Processando fixture 123 · 3 casa(s)'))
      .toEqual({ tipo: 'normal', texto: 'Processando fixture 123 · 3 casa(s)', marca: 'ODDS' })
  })
  it('a mesma marca tem sempre a mesma cor', () => {
    expect(corDaMarca('VIP_ENGINE')).toBe(corDaMarca('VIP_ENGINE'))
  })
})
