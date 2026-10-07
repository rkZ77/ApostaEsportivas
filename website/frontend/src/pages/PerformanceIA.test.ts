import { describe, expect, it } from 'vitest'
import { curvaAcumulada } from './PerformanceIA'

describe('curva do CLV', () => {
  it('é a média acumulada, pulando pick sem CLV', () => {
    expect(curvaAcumulada([{ clv: 2 }, { clv: null }, { clv: 4 }, { clv: -3 }])).toEqual([2, 3, 1])
  })
})
