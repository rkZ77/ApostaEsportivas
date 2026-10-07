import { describe, expect, it } from 'vitest'
import { nomeDaLigaPt, rotuloDaRodada } from './paisDaLiga'

describe('rodada em português', () => {
  it.each([
    ['Regular Season - 29', 'Rodada 29'],
    ['Round of 16 - 1st Leg', 'Oitavas de final · Ida'],
    ['Quarter-finals - 2nd Leg', 'Quartas de final · Volta'],
    ['Semi-finals', 'Semifinal'],
    ['Final', 'Final'],
    ['Group A - 3', 'Grupo A · Rodada 3'],
    ['Group Stage - 2', 'Fase de grupos · Rodada 2'],
    ['League Stage - 5', 'Fase de liga · Rodada 5'],
    ['3rd Qualifying Round - 1st Leg', '3ª fase de qualificação · Ida'],
    ['2nd Round', '2ª fase'],
    ['Apertura - 7', 'Apertura · Rodada 7'],
  ])('%s → %s', (bruto, esperado) => {
    expect(rotuloDaRodada(bruto)).toBe(esperado)
  })

  it('forma desconhecida volta como veio, e vazio fica vazio', () => {
    expect(rotuloDaRodada('Relegation Round - 2')).toBe('Relegation Round - 2')
    expect(rotuloDaRodada(null)).toBe('')
  })
})

describe('nome da liga em português', () => {
  it('liga conhecida pelo nome do torcedor; desconhecida pelo gravado', () => {
    expect(nomeDaLigaPt(71, 'Serie A')).toBe('Brasileirão Série A')
    expect(nomeDaLigaPt(135, 'Serie A')).toBe('Campeonato Italiano')
    expect(nomeDaLigaPt(9999, 'Liga Qualquer')).toBe('Liga Qualquer')
  })
})
