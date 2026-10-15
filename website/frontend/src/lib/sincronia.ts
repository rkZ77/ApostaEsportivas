/*
 * Sincronia entre telas · o que uma ação muda, toda tela aberta fica sabendo.
 *
 * O DEFEITO (relatado em 06/10/2026). Em /picks, pegar o bilhete virava o
 * botão em "Bilhete registrado" e, ao trocar de aba ou de dia e voltar, ele
 * era "Pegar bilhete" de novo · até o F5. Cada tela baixa a sua lista uma vez
 * e cada card guardava o "já peguei" na própria memória. Card recriado lia a
 * lista antiga, que nunca soube da aposta. O mesmo valia pra qualquer escrita:
 * nada avisava as outras telas de que o dado delas tinha ficado velho.
 *
 * O QUE ESTE MÓDULO FAZ. Duas coisas, ambas alimentadas por services/api.ts,
 * que é por onde passa TODA escrita do site:
 *
 *   1. Registro de bilhetes. POST /banca/follow que deu certo grava o pick
 *      aqui; DELETE /banca/follow/... apaga. Card nenhum precisa lembrar de
 *      avisar ninguém, e card nenhum depende de a lista da tela ter sido
 *      recarregada pra mostrar o estado certo · ver `useBilhete`.
 *
 *   2. Versão dos dados. Toda escrita que deu certo, e toda volta à aba do
 *      navegador depois de um tempo fora, sobe um contador. Tela que lista algo
 *      põe `useVersaoDosDados()` nas dependências do efeito que busca a lista e
 *      passa a recarregar sozinha · ver o uso em pages/Picks.tsx.
 *
 * Não é cache de dados (isso seria o TanStack Query, e a troca do site inteiro
 * pra ele é outro passo). É o mínimo pra que nenhuma tela mostre estado velho
 * depois de uma ação feita em outra.
 */
import { useEffect, useRef, useState, useSyncExternalStore } from 'react'

/* ── 1. Bilhetes ─────────────────────────────────────────────────────────── */

export interface BilheteLocal {
  stakeUnits: number | null
  actualOdd: number | null
  betHouse: string | null
}

/** null = desfeito nesta sessão (vence o `is_followed` velho da lista). */
const bilhetes = new Map<string, BilheteLocal | null>()
const ouvintesBilhete = new Set<() => void>()
let versaoBilhetes = 0

/* `vip` e `multiplas` são os nomes que a API usa em alguns lugares e o card em
   outros · a chave normaliza pra que os dois lados se encontrem. */
function chave(tipo: string | null | undefined, id: number | string): string {
  const t = (tipo || 'vip').replace(/^multipla$/, 'multiplas')
  return `${t}:${id}`
}

function avisarBilhetes() {
  versaoBilhetes++
  ouvintesBilhete.forEach(f => f())
}

export function marcarBilhete(tipo: string, id: number | string, dados: BilheteLocal) {
  bilhetes.set(chave(tipo, id), dados)
  avisarBilhetes()
}

export function desmarcarBilhete(tipo: string, id: number | string) {
  bilhetes.set(chave(tipo, id), null)
  avisarBilhetes()
}

function assinarBilhetes(f: () => void) {
  ouvintesBilhete.add(f)
  return () => { ouvintesBilhete.delete(f) }
}

/**
 * O que esta sessão sabe do bilhete deste pick.
 *
 * `undefined` = nada aconteceu aqui, vale o que a API trouxe (`is_followed`).
 * Objeto = pegou nesta sessão. `null` = desfez nesta sessão.
 */
export function useBilhete(tipo: string | null | undefined, id: number | string | null | undefined) {
  useSyncExternalStore(assinarBilhetes, () => versaoBilhetes, () => 0)
  if (id == null) return undefined
  return bilhetes.get(chave(tipo, id))
}

/** Mesma leitura, fora de componente (filtros e contagens de lista). */
export function bilheteDe(tipo: string | null | undefined, id: number | string) {
  return bilhetes.get(chave(tipo, id))
}

/* ── 2. Versão dos dados ─────────────────────────────────────────────────── */

let versaoDados = 0
const ouvintesDados = new Set<() => void>()

function subirVersao() {
  versaoDados++
  ouvintesDados.forEach(f => f())
}

/*
 * Escritas em rajada (o /admin salva três campos seguidos, o card registra e
 * em seguida busca a banca) viram UMA recarga · senão cada tela aberta pediria
 * a lista três vezes no mesmo segundo.
 */
let agendada: number | null = null
export function avisarEscrita() {
  if (agendada != null) return
  agendada = window.setTimeout(() => { agendada = null; subirVersao() }, 250)
}

/*
 * Voltar pra aba depois de 60 s fora também conta como dado velho: é o caso de
 * quem deixa o /picks aberto, aposta pelo celular e volta pro computador.
 * Menos que isso é troca rápida de aba, e recarregar ali só gastaria rede.
 */
const FORA_MINIMO_MS = 60_000
let saiuEm: number | null = null
if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') { saiuEm = Date.now(); return }
    if (saiuEm != null && Date.now() - saiuEm >= FORA_MINIMO_MS) subirVersao()
    saiuEm = null
  })
}

function assinarDados(f: () => void) {
  ouvintesDados.add(f)
  return () => { ouvintesDados.delete(f) }
}

/** A versão de agora, fora de componente. */
export function versaoDosDados(): number {
  return versaoDados
}

/** Número que muda quando o dado do servidor pode ter mudado. */
export function useVersaoDosDados(): number {
  return useSyncExternalStore(assinarDados, () => versaoDados, () => 0)
}

/**
 * Chama `recarregar` a cada mudança de versão, MENOS na montagem · a primeira
 * busca continua sendo do efeito normal da tela, com o esqueleto dela. Esta é
 * a recarga silenciosa, por cima do que já está na tela.
 */
export function useRecarregarQuandoMudar(recarregar: () => void) {
  const versao = useVersaoDosDados()
  const [inicial] = useState(versao)
  useEffect(() => {
    if (versao !== inicial) recarregar()
    // `recarregar` fora de propósito: a tela passa uma função nova a cada
    // render, e o gatilho aqui é só a versão.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [versao])
}

/**
 * QUEM FICA OLHANDO A TELA (15/10/2026, pedido do usuário: "não atualiza se eu
 * não atualizo a página"). A versão acima cobre ação e volta à aba; não cobre
 * quem deixa /picks aberto esperando o jogo acabar · o card ficava "pendente"
 * até o F5.
 *
 * Chama `recarregar` a cada `ms` enquanto `ativo` (a tela diz quando vale:
 * pick sem resultado com o jogo já começado) e a aba estiver visível. Aba
 * escondida não gasta requisição; a volta a ela já recarrega pela versão.
 */
export function useRecarregarEnquanto(ativo: boolean, ms: number, recarregar: () => void) {
  const ref = useRef(recarregar)
  ref.current = recarregar
  useEffect(() => {
    if (!ativo) return
    const t = window.setInterval(() => { if (!document.hidden) ref.current() }, ms)
    return () => window.clearInterval(t)
  }, [ativo, ms])
}

/**
 * Há, em `dados`, algum pick SEM resultado cujo jogo já começou? Varre a
 * estrutura inteira (listas e objetos), porque cada produto guarda o pick num
 * formato · procura `result` vazio ao lado de um horário já passado
 * (`match_datetime`, ou o de uma das pernas em `games`/`legs`).
 */
export function temPendenteRolando(dados: unknown, agora = Date.now()): boolean {
  /* O banco grava o horário de Brasília SEM fuso ("2026-10-15 21:30:00" · os
     cards cortam o texto e mostram 21:30). Sem fuso no texto, ele é lido como
     -03:00, e não no fuso do aparelho de quem abriu. */
  const instante = (s: string) =>
    /([zZ]|[+-]\d{2}:?\d{2})$/.test(s) ? Date.parse(s) : Date.parse(`${s.replace(' ', 'T').slice(0, 19)}-03:00`)
  const comecou = (v: unknown) => typeof v === 'string' && !Number.isNaN(instante(v)) && instante(v) <= agora
  const visitar = (x: unknown, profundidade: number): boolean => {
    if (!x || typeof x !== 'object' || profundidade > 6) return false
    if (Array.isArray(x)) return x.some(i => visitar(i, profundidade + 1))
    const o = x as Record<string, unknown>
    if ('result' in o && (o.result == null || o.result === '')) {
      if (comecou(o.match_datetime) || comecou(o.kickoff)) return true
      for (const k of ['games', 'legs', 'pernas']) {
        const p = o[k]
        if (Array.isArray(p) && p.some(g => g && typeof g === 'object'
            && (comecou((g as any).match_datetime) || comecou((g as any).kickoff)))) return true
      }
    }
    return Object.values(o).some(v => visitar(v, profundidade + 1))
  }
  return visitar(dados, 0)
}
