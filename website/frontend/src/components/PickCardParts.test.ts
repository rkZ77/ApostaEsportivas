import { describe, expect, it } from 'vitest'
import { numeroDaLinha } from './PickCardParts'

describe('número da linha', () => {
  it('lê a linha em inglês, em português e com vírgula', () => {
    expect(numeroDaLinha('Under 26.5')).toBe(26.5)
    expect(numeroDaLinha('Menos de 26,5')).toBe(26.5)
    expect(numeroDaLinha('Over 9')).toBe(9)
    expect(numeroDaLinha(null)).toBeNull()
  })
})
