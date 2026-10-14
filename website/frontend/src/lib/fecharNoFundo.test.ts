import { describe, expect, it, vi } from 'vitest'
import type { MouseEvent } from 'react'
import { fecharNoFundo } from './fecharNoFundo'

const fundo = { dataset: {} as Record<string, string> }
const campo = {}
const ev = (target: object) => ({ target, currentTarget: fundo }) as unknown as MouseEvent<HTMLElement>

describe('fecharNoFundo', () => {
  it('fecha quando aperta e solta no fundo', () => {
    const fechar = vi.fn()
    const h = fecharNoFundo(fechar)
    h.onMouseDown(ev(fundo)); h.onClick(ev(fundo))
    expect(fechar).toHaveBeenCalledTimes(1)
  })

  it('não fecha quando a seleção começa no campo e solta no fundo', () => {
    const fechar = vi.fn()
    const h = fecharNoFundo(fechar)
    h.onMouseDown(ev(campo)); h.onClick(ev(fundo))
    expect(fechar).not.toHaveBeenCalled()
  })
})
