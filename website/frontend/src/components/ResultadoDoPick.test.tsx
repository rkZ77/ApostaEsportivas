import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import ResultadoDoPick from './ResultadoDoPick'

const html = (p: Partial<Parameters<typeof ResultadoDoPick>[0]>) => renderToStaticMarkup(
  <ResultadoDoPick result="RED" odd={1.5} stakeSeguida={null} stakePlano={2} {...p} />)

describe('ResultadoDoPick', () => {
  it('quem não apostou: resultado do pick, sem cor e sem reais', () => {
    const h = html({ banca: { unit_value: 10 } })
    expect(h).toContain('Resultado do pick')
    expect(h).toContain('você não apostou')
    expect(h).toContain('-2.00u')
    expect(h).not.toContain('text-red-400')
    expect(h).not.toContain('Em reais')
  })

  it('quem apostou: seu lucro, com cor e em reais', () => {
    const h = html({ result: 'GREEN', stakeSeguida: 3, banca: { unit_value: 10 } })
    expect(h).toContain('Seu lucro')
    expect(h).toContain('text-green-400')
    expect(h).toContain('Em reais')
    expect(h).toContain('+R$15')
  })

  it('produto sem stake de plano não estampa +0,00u', () => {
    expect(html({ stakePlano: 0, contaEmUnidades: false })).toContain('só conta apostado')
  })
})
