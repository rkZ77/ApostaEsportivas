import { useMemo, useState } from 'react'
import { ArrowDownWideNarrow, Flag, Layers, ShieldHalf } from 'lucide-react'
import { SearchInput, PillGroup, Badge } from './ui'

/*
 * Controles da aba Mercados.
 *
 * A aba listava faltas e defesas em duas seções fixas, sem busca nem recorte.
 * Em dia cheio isso vira uma rolagem longa onde achar "o jogo do Palmeiras" ou
 * "o que tem mais margem" só dá na força do olho.
 *
 * Tudo aqui é client-side de propósito: a aba já baixa os dois conjuntos
 * inteiros de uma vez (são poucas dezenas de picks por dia), então filtrar no
 * servidor só somaria ida e volta.
 */

export type MercadoCategoria = 'todos' | 'faltas' | 'goleiros'
export type MercadoOrdem = 'margem' | 'odd' | 'data'
export type MercadoEstado = 'todos' | 'pendentes' | 'resolvidos'

export interface Filtravel {
  home_team: string
  away_team: string
  player_name?: string
  team_name?: string
  market: string
  line: string
  odd: number
  edge?: number
  match_date: string
  result?: string | null
}

export interface MercadoFiltro {
  busca: string
  categoria: MercadoCategoria
  ordem: MercadoOrdem
  estado: MercadoEstado
}

export const FILTRO_INICIAL: MercadoFiltro = {
  busca: '', categoria: 'todos', ordem: 'margem', estado: 'todos',
}

/** Normaliza pra busca tolerar acento: "sao paulo" acha "São Paulo".
    O intervalo vai escrito como escape (\u0300-\u036f, os diacríticos
    combinantes) e não como caractere literal: literal aqui é invisível no
    editor e não sobrevive a uma conversão de encoding. */
const norm = (s: string) =>
  s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()

export function aplicarFiltro<T extends Filtravel>(
  picks: T[],
  f: MercadoFiltro,
): T[] {
  let out = picks


  if (f.busca.trim()) {
    const q = norm(f.busca.trim())
    out = out.filter(p =>
      [p.home_team, p.away_team, p.player_name, p.team_name, p.market, p.line]
        .filter(Boolean)
        .some(v => norm(String(v)).includes(q)),
    )
  }

  if (f.estado === 'pendentes')  out = out.filter(p => !p.result)
  if (f.estado === 'resolvidos') out = out.filter(p => !!p.result)

  // Cópia antes de ordenar: sort muta, e o array vem direto do state.
  return [...out].sort((a, b) => {
    if (f.ordem === 'odd')  return Number(b.odd) - Number(a.odd)
    if (f.ordem === 'data') return a.match_date.localeCompare(b.match_date)
    return (Number(b.edge ?? 0)) - (Number(a.edge ?? 0))
  })
}

export default function MercadosControls({
  filtro,
  onChange,
  totalFaltas,
  totalGoleiros,
  visiveis,
}: {
  filtro: MercadoFiltro
  onChange: (f: MercadoFiltro) => void
  totalFaltas: number
  totalGoleiros: number
  /** Quantos sobraram depois do filtro, pra dar retorno imediato à busca. */
  visiveis: number
}) {
  const set = <K extends keyof MercadoFiltro>(k: K, v: MercadoFiltro[K]) =>
    onChange({ ...filtro, [k]: v })

  const total = totalFaltas + totalGoleiros
  const filtrando =
    filtro.busca.trim() !== '' || filtro.estado !== 'todos'
    || filtro.categoria !== 'todos'

  const categorias = useMemo(() => ([
    { value: 'todos'    as const, label: <span className="flex items-center gap-1.5"><Layers className="w-3 h-3" />Todos <span className="text-ink-4">{total}</span></span> },
    { value: 'faltas'   as const, label: <span className="flex items-center gap-1.5"><Flag className="w-3 h-3" />Faltas <span className="text-ink-4">{totalFaltas}</span></span> },
    { value: 'goleiros' as const, label: <span className="flex items-center gap-1.5"><ShieldHalf className="w-3 h-3" />Defesas <span className="text-ink-4">{totalGoleiros}</span></span> },
  ]), [total, totalFaltas, totalGoleiros])

  return (
    <div className="space-y-3 mb-6">
      <SearchInput
        value={filtro.busca}
        onChange={v => set('busca', v)}
        placeholder="Buscar time, goleiro ou linha"
        label="Buscar nos mercados"
      />

      <PillGroup options={categorias} value={filtro.categoria} onChange={v => set('categoria', v)} />

      <div className="flex items-center justify-between gap-3 flex-wrap">
        <PillGroup
          options={[
            { value: 'todos'      as const, label: 'Todos' },
            { value: 'pendentes'  as const, label: 'Pendentes' },
            { value: 'resolvidos' as const, label: 'Resolvidos' },
          ]}
          value={filtro.estado}
          onChange={v => set('estado', v)}
        />

        <label className="flex items-center gap-1.5 text-[11px] text-ink-4 shrink-0">
          <ArrowDownWideNarrow className="w-3.5 h-3.5" />
          <span className="sr-only sm:not-sr-only">Ordenar por</span>
          <select
            value={filtro.ordem}
            onChange={e => set('ordem', e.target.value as MercadoOrdem)}
            className="bg-surface-2 border border-line-strong rounded-md px-2 py-1 text-[11px] text-ink-2 focus:outline-none focus:border-accent cursor-pointer"
          >
            <option value="margem">Maior margem</option>
            <option value="odd">Maior odd</option>
            <option value="data">Data do jogo</option>
          </select>
        </label>
      </div>

      {filtrando && (
        <div className="flex items-center gap-2">
          <Badge tone={visiveis > 0 ? 'green' : 'neutral'}>
            {visiveis} {visiveis === 1 ? 'resultado' : 'resultados'}
          </Badge>
          <button
            onClick={() => onChange(FILTRO_INICIAL)}
            className="text-[11px] text-ink-4 hover:text-ink-2 transition-colors"
          >
            Limpar filtros
          </button>
        </div>
      )}
    </div>
  )
}
