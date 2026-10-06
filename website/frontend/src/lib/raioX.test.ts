// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest'
import { ambasMarcam, fraseDoJogador, ESTATS_DE_JOGADOR, numero, resultadoDoJogo, rotuloDaLinha, taxa,
         taxaDoJogador, type Jogador, type JogoDoTime } from './raioX'
import { adicionar, chanceCombinada, limpar, remover, textoDoBilhete, type Selecao } from './bilheteMontado'

const jogo = (p: Partial<JogoDoTime>): JogoDoTime => ({
  fixture_id: 1, data: null, em_casa: true, adversario_id: 2,
  gols_pro: 1, gols_contra: 1, escanteios_pro: 5, escanteios_contra: 5,
  amarelos_pro: 2, amarelos_contra: 2, vermelhos_pro: 0, vermelhos_contra: 0,
  chutes_alvo_pro: 4, chutes_alvo_contra: 3, faltas_pro: 10, faltas_contra: 12, posse: 50, ...p,
})

describe('taxa', () => {
  it('conta acima e abaixo da linha', () => {
    expect(taxa([3, 1, 4, 0], 2.5, 'mais')).toMatchObject({ bateu: 2, n: 4, pct: 0.5 })
    expect(taxa([3, 1, 4, 0], 2.5, 'menos')).toMatchObject({ bateu: 2, n: 4 })
  })

  it('jogo sem dado não conta nem a favor nem contra', () => {
    expect(taxa([3, null, 4], 2.5, 'mais')).toMatchObject({ bateu: 2, n: 2, pct: 1 })
  })

  it('linha cheia empatada é devolução: sai da amostra', () => {
    const t = taxa([10, 10, 11, 9], 10, 'mais')
    expect(t).toMatchObject({ bateu: 1, n: 2 })
    expect(t.media).toBe(10)
  })

  it('sem amostra não inventa porcentagem', () => {
    expect(taxa([null, null], 2.5, 'mais')).toMatchObject({ n: 0, pct: null, media: null })
  })
})

describe('rótulos', () => {
  it('linha .5 e linha inteira', () => {
    expect(rotuloDaLinha(9.5, 'mais')).toBe('Mais de 9.5')
    expect(rotuloDaLinha(10, 'menos')).toBe('Menos de 10')
  })

  it('jogador no singular e no plural', () => {
    const alvo = ESTATS_DE_JOGADOR.find(e => e.id === 'chutes_alvo')!
    expect(fraseDoJogador(alvo, 1)).toBe('1+ chute no alvo')
    expect(fraseDoJogador(alvo, 2)).toBe('2+ chutes no alvo')
  })
})

describe('jogo', () => {
  it('ambas marcam e resultado do ponto de vista do time', () => {
    expect(ambasMarcam(jogo({ gols_pro: 2, gols_contra: 1 }))).toBe(true)
    expect(ambasMarcam(jogo({ gols_pro: 2, gols_contra: 0 }))).toBe(false)
    expect(ambasMarcam(jogo({ gols_contra: null }))).toBeNull()
    expect(resultadoDoJogo(jogo({ gols_pro: 0, gols_contra: 2 }))).toBe('D')
  })

  it('"2+ chutes no alvo" é valor >= 2 em cada jogo do jogador', () => {
    const j = { jogos: [{ chutes_alvo: 2 }, { chutes_alvo: 1 }, { chutes_alvo: 3 }, { chutes_alvo: null }] } as unknown as Jogador
    expect(taxaDoJogador(j, 'chutes_alvo', 2)).toMatchObject({ bateu: 2, n: 3 })
  })
})

describe('numero: faz, cede e tempo do jogo', () => {
  const j = jogo({ escanteios_pro: 7, escanteios_contra: 3, escanteios_pro_1t: 4, escanteios_contra_1t: 1,
                   faltas_pro: 10, faltas_contra: 12 })

  it('faz, cede e jogo', () => {
    expect(numero(j, 'escanteios', 'pro', 'total')).toBe(7)
    expect(numero(j, 'escanteios', 'contra', 'total')).toBe(3)
    expect(numero(j, 'escanteios', 'jogo', 'total')).toBe(10)
  })

  it('1º tempo da folha e 2º tempo por subtração', () => {
    expect(numero(j, 'escanteios', 'pro', '1t')).toBe(4)
    expect(numero(j, 'escanteios', 'jogo', '1t')).toBe(5)
    expect(numero(j, 'escanteios', 'pro', '2t')).toBe(3)
    expect(numero(j, 'escanteios', 'contra', '2t')).toBe(2)
  })

  it('sem folha do 1º tempo não inventa número', () => {
    expect(numero(jogo({}), 'escanteios', 'pro', '1t')).toBeNull()
    expect(numero(jogo({}), 'escanteios', 'jogo', '2t')).toBeNull()
    expect(numero(j, 'faltas', 'pro', '1t')).toBeNull()
  })
})

describe('bilhete montado', () => {
  const sel = (id: string, bateu: number, n: number): Selecao =>
    ({ id, fixture_id: 1, jogo: 'Casa x Fora', descricao: id, bateu, n })

  beforeEach(() => limpar())

  it('a mesma seleção não entra duas vezes e sai pelo id', () => {
    adicionar(sel('a', 7, 10)); adicionar(sel('a', 7, 10)); adicionar(sel('b', 5, 10))
    expect(JSON.parse(localStorage.getItem('pickia_bilhete_montado')!)).toHaveLength(2)
    remover('a')
    expect(JSON.parse(localStorage.getItem('pickia_bilhete_montado')!)).toHaveLength(1)
  })

  it('chance combinada multiplica as taxas, e some sem amostra', () => {
    expect(chanceCombinada([sel('a', 8, 10), sel('b', 5, 10)])).toBeCloseTo(0.4)
    expect(chanceCombinada([sel('a', 8, 10), sel('b', 0, 0)])).toBeNull()
    expect(chanceCombinada([])).toBeNull()
  })

  it('texto agrupa por jogo e leva a evidência', () => {
    const t = textoDoBilhete([sel('Escanteios · Mais de 9.5', 7, 10)])
    expect(t).toContain('Casa x Fora')
    expect(t).toContain('(7/10 nos últimos jogos)')
  })
})
