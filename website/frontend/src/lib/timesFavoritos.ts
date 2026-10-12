import { useEffect, useState } from 'react'
import api from '../services/api'

/*
 * Times favoritos (12/10/2026) · a estrela do Raio-X e o grupo "Seus times"
 * no topo da aba Jogos. Fica na conta (routers/personal.py), e não no
 * navegador: o site é usado no celular e no PC.
 *
 * Um estado só pro app inteiro: marcar no Raio-X (painel do PC, ao lado da
 * lista) tem que reordenar a lista na hora, sem recarregar.
 */

let favoritos: number[] | null = null
let pedido: Promise<void> | null = null
const ouvintes = new Set<(v: number[]) => void>()

function avisar() {
  ouvintes.forEach(f => f(favoritos ?? []))
}

function carregar(): Promise<void> {
  if (!pedido) {
    pedido = api.get('/personal/times-favoritos')
      .then(r => { favoritos = r.data?.times ?? [] })
      .catch(() => { favoritos = favoritos ?? [] })
      .finally(avisar)
  }
  return pedido
}

export function useTimesFavoritos() {
  const [lista, setLista] = useState<number[]>(favoritos ?? [])

  useEffect(() => {
    ouvintes.add(setLista)
    if (favoritos === null) carregar()
    else setLista(favoritos)
    return () => { ouvintes.delete(setLista) }
  }, [])

  const alternar = (teamId: number) => {
    const marcar = !(favoritos ?? []).includes(teamId)
    const antes = favoritos ?? []
    // Otimista: a estrela acende no toque; volta se o servidor recusar.
    favoritos = marcar ? [...antes, teamId] : antes.filter(id => id !== teamId)
    avisar()
    api.put('/personal/times-favoritos', { team_id: teamId, favorito: marcar })
      .then(r => { favoritos = r.data?.times ?? favoritos; avisar() })
      .catch(() => { favoritos = antes; avisar() })
  }

  return { favoritos: lista, ehFavorito: (id?: number | null) => !!id && lista.includes(id), alternar }
}

/** Separa os jogos com time favorito, mantendo a ordem de cada parte. */
export function separarFavoritos<T extends { home_team_id?: number | null; away_team_id?: number | null }>(
  jogos: T[], favoritos: number[],
): { dosFavoritos: T[]; resto: T[] } {
  const fav = new Set(favoritos)
  const dosFavoritos: T[] = []
  const resto: T[] = []
  for (const j of jogos) {
    ((j.home_team_id && fav.has(j.home_team_id)) || (j.away_team_id && fav.has(j.away_team_id))
      ? dosFavoritos : resto).push(j)
  }
  return { dosFavoritos, resto }
}
