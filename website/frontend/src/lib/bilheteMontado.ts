/*
 * O bilhete que a pessoa monta na aba Jogos (2026-10-06).
 *
 * Não é aposta registrada (isso é /banca/follow): é a lista de seleções que
 * ela está juntando enquanto pesquisa, de um jogo ou de vários, pra levar pra
 * casa de aposta. Mora no navegador, sobrevive a recarregar e a trocar de
 * jogo, e some quando ela limpa.
 *
 * localStorage, e não servidor, de propósito: é rascunho de uma pessoa num
 * aparelho, e não precisa de conta nem de rede pra funcionar.
 */
import { useSyncExternalStore } from 'react'
import type { FonteDaChance } from './chanceAjustada'

/**
 * A seleção do jeito que o backend sabe liquidar (bilhete_pessoal.validar_pernas).
 * É ela que vai pra banca quando a pessoa registra o bilhete; `descricao` é só
 * o texto que a pessoa leu.
 */
export type Perna =
  | { tipo: 'time'; mercado: string; direcao?: 'mais' | 'menos'; linha?: number
      periodo?: 'total' | '1t' | '2t'; lado_time?: 'home' | 'away'
      /** Só no mercado 'resultado': 1, X, 2, 1X, 12 ou X2. */
      escolha?: string
      /** Só em 'ambas_cartao': cartões mínimos de CADA time (1 ou 2). */
      minimo?: number }
  | { tipo: 'jogador'; estat: string; minimo: number; player_id: number; player_name: string }

export interface PernaCompleta {
  fixture_id: number; home_team_id: number; away_team_id: number
  home: string; away: string; descricao: string
  /** Odd da casa quando entrou no bilhete · o backend usa pra recalcular o
   *  lucro quando uma seleção é anulada. */
  odd?: number
}

export interface Selecao {
  /** Estável por seleção: o mesmo mercado no mesmo jogo não entra duas vezes. */
  id: string
  fixture_id: number
  jogo: string
  /** "Escanteios no jogo · Mais de 9.5" ou "Hulk · 1+ chute no alvo". */
  descricao: string
  /** Em quantos dos últimos jogos bateu · é a evidência que a pessoa viu. */
  bateu: number
  n: number
  player_id?: number
  /** Melhor odd da casa quando a seleção entrou no bilhete (07/10). Só mercado
   *  que a coleta traz; chute no alvo, falta e jogador ficam sem. */
  odd?: number
  casa?: string | null
  /** Chance ajustada (lib/chanceAjustada) quando a seleção entrou · 0..1. Ausente
   *  nas seleções salvas antes de 18/10 e onde não há preço nem média da liga. */
  chance?: number
  fonte_chance?: FonteDaChance
  /** Ausente nas seleções salvas antes de 06/10: essas não vão pra banca. */
  perna?: Perna & PernaCompleta
}

/** As seleções que dá pra registrar na banca (têm a perna estruturada). */
export const registraveis = (lista: Selecao[]) => lista.filter(s => s.perna)

const CHAVE = 'pickia_bilhete_montado'
const MAXIMO = 20

let selecoes: Selecao[] = ler()
const ouvintes = new Set<() => void>()

function ler(): Selecao[] {
  try {
    const bruto = localStorage.getItem(CHAVE)
    const lista = bruto ? JSON.parse(bruto) : []
    return Array.isArray(lista) ? lista.slice(0, MAXIMO) : []
  } catch {
    return []
  }
}

function gravar(nova: Selecao[]) {
  selecoes = nova
  try { localStorage.setItem(CHAVE, JSON.stringify(nova)) } catch { /* modo privado: fica só na memória */ }
  ouvintes.forEach(f => f())
}

export function adicionar(s: Selecao) {
  if (selecoes.some(x => x.id === s.id)) return
  gravar([...selecoes, s].slice(-MAXIMO))
}

export function remover(id: string) {
  gravar(selecoes.filter(s => s.id !== id))
}

export function alternar(s: Selecao) {
  if (selecoes.some(x => x.id === s.id)) remover(s.id)
  else adicionar(s)
}

/**
 * Põe `s` tirando antes as seleções do mesmo grupo (ids que começam com
 * `grupo`). É o "um resultado por jogo" da casa (09/10): Lens vence, empate e
 * Lyon vence no mesmo bilhete é aposta que perde sempre. Já dentro, tira.
 */
export function trocarNoGrupo(s: Selecao, grupo: string) {
  if (selecoes.some(x => x.id === s.id)) return remover(s.id)
  gravar([...selecoes.filter(x => !x.id.startsWith(grupo)), s].slice(-MAXIMO))
}

export function limpar() {
  gravar([])
}

/* Outra aba do mesmo navegador mexeu no bilhete: segue junto. */
if (typeof window !== 'undefined') {
  window.addEventListener('storage', e => {
    if (e.key === CHAVE) { selecoes = ler(); ouvintes.forEach(f => f()) }
  })
}

function assinar(f: () => void) {
  ouvintes.add(f)
  return () => { ouvintes.delete(f) }
}

export function useBilheteMontado(): Selecao[] {
  return useSyncExternalStore(assinar, () => selecoes, () => selecoes)
}

/**
 * Chance de TODAS baterem, se fossem independentes, pela chance AJUSTADA de
 * cada seleção (18/10/2026).
 *
 * Era o produto do bateu/n cru: 8/8 × 6/6 dava "100%" num bilhete que o
 * preço e o motor davam ~40%. Agora null quando alguma seleção não tem chance
 * ajustada (salva antes de 18/10, ou mercado sem preço nem média da liga):
 * a tela diz quantas ficaram sem, em vez de inventar o número.
 *
 * Seleções do mesmo jogo andam juntas (jogo de muitos gols tem mais chutes no
 * alvo), então no mesmo jogo isto é aproximação · a tela avisa.
 */
export function chanceCombinada(lista: Selecao[]): number | null {
  if (!lista.length || lista.some(s => s.chance == null)) return null
  return lista.reduce((p, s) => p * (s.chance as number), 1)
}

/** Quantas seleções estão sem chance ajustada · é o que a bandeja explica. */
export const semChance = (lista: Selecao[]) => lista.filter(s => s.chance == null).length

/**
 * Odd do bilhete pelo produto das odds das casas. Só quando TODAS as seleções
 * têm odd: com uma faltando, o produto seria menor que o real e enganaria.
 * É estimativa (a casa pode pagar outro valor no combinado), por isso a tela
 * sugere e a pessoa confirma o número que a casa mostrou.
 */
export function oddCombinada(lista: Selecao[]): number | null {
  if (!lista.length || lista.some(s => !s.odd)) return null
  return Math.round(lista.reduce((p, s) => p * (s.odd as number), 1) * 100) / 100
}

/** Texto pra copiar e colar na casa de aposta ou no WhatsApp. */
export function textoDoBilhete(lista: Selecao[]): string {
  const porJogo = new Map<string, Selecao[]>()
  for (const s of lista) porJogo.set(s.jogo, [...(porJogo.get(s.jogo) ?? []), s])
  const blocos = [...porJogo].map(([jogo, ss]) =>
    `${jogo}\n${ss.map(s => `• ${s.descricao}${s.odd ? ` @ ${s.odd.toFixed(2)}` : ''} (${s.bateu}/${s.n} nos últimos jogos${s.chance != null ? `, chance estimada ${Math.round(s.chance * 100)}%` : ''})`).join('\n')}`)
  return `Meu bilhete no Pick IA\n\n${blocos.join('\n\n')}`
}
