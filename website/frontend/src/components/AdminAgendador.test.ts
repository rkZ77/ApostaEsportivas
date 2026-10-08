import { describe, expect, it } from 'vitest'
import { leituraDaMedicao } from './AdminAgendador'

describe('leituraDaMedicao', () => {
  it('pega o veredito depois de "=== Leitura ==="', () => {
    const saida = 'tabela...\n\n=== Leitura ===\n  1o tempo PERDE dinheiro com margem: desligar (MOTOR_1T=off).\n'
    expect(leituraDaMedicao(saida)).toBe('1o tempo PERDE dinheiro com margem: desligar (MOTOR_1T=off).')
  })
  it('junta várias linhas do veredito', () => {
    expect(leituraDaMedicao('=== Leitura ===\nlinha um\n  linha dois')).toBe('linha um linha dois')
  })
  it('sem veredito no texto, nada', () => {
    expect(leituraDaMedicao('só tabela')).toBeNull()
    expect(leituraDaMedicao(undefined)).toBeNull()
  })
})
