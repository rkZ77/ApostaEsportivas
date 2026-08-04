import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import api from '../services/api'
import { useAuth } from './AuthContext'

/*
 * Favoritos do usuário, num contexto só.
 *
 * É contexto e não hook por tela porque o coração aparece em muitos lugares ao
 * mesmo tempo (card de pick, linha de liga, aba Mercados). Com hook por
 * componente, cada coração faria a sua própria chamada e favoritar num lugar
 * não atualizaria o mesmo item renderizado em outro.
 *
 * A escrita é otimista: o coração muda na hora e desfaz sozinho se a API
 * recusar. Numa lista longa, esperar o ida e volta faz o clique parecer morto.
 */

export type FavoriteKind = 'league' | 'team' | 'market' | 'pick'

interface Favorite {
  id: number
  kind: FavoriteKind
  ref_id: string
  label: string | null
}

interface FavoritesValue {
  favorites: Favorite[]
  loaded: boolean
  isFavorite: (kind: FavoriteKind, refId: string | number) => boolean
  toggle: (kind: FavoriteKind, refId: string | number, label?: string) => Promise<void>
  byKind: (kind: FavoriteKind) => Favorite[]
  count: number
}

const Ctx = createContext<FavoritesValue | null>(null)

const key = (kind: string, refId: string | number) => `${kind}:${refId}`

export function FavoritesProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  const [favorites, setFavorites] = useState<Favorite[]>([])
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (!user) {
      setFavorites([])
      setLoaded(true)
      return
    }
    let alive = true
    api.get('/personal/favorites')
      .then(r => { if (alive) setFavorites(r.data ?? []) })
      .catch(() => { /* favorito é acessório: falhar aqui não trava a tela */ })
      .finally(() => { if (alive) setLoaded(true) })
    return () => { alive = false }
  }, [user?.id])

  const index = useMemo(
    () => new Set(favorites.map(f => key(f.kind, f.ref_id))),
    [favorites],
  )

  const isFavorite = useCallback(
    (kind: FavoriteKind, refId: string | number) => index.has(key(kind, refId)),
    [index],
  )

  const toggle = useCallback(async (kind: FavoriteKind, refId: string | number, label?: string) => {
    if (!user) return
    const ref = String(refId)
    const wasFav = index.has(key(kind, ref))
    const snapshot = favorites

    // otimista
    setFavorites(prev => wasFav
      ? prev.filter(f => !(f.kind === kind && f.ref_id === ref))
      : [...prev, { id: -Date.now(), kind, ref_id: ref, label: label ?? null }])

    try {
      if (wasFav) {
        await api.delete(`/personal/favorites/${kind}/${encodeURIComponent(ref)}`)
      } else {
        const { data } = await api.post('/personal/favorites', { kind, ref_id: ref, label })
        // troca o id provisório pelo do banco
        setFavorites(prev => prev.map(f =>
          f.kind === kind && f.ref_id === ref ? { ...f, id: data.id } : f))
      }
    } catch {
      setFavorites(snapshot)
    }
  }, [user, index, favorites])

  const byKind = useCallback(
    (kind: FavoriteKind) => favorites.filter(f => f.kind === kind),
    [favorites],
  )

  const value = useMemo<FavoritesValue>(
    () => ({ favorites, loaded, isFavorite, toggle, byKind, count: favorites.length }),
    [favorites, loaded, isFavorite, toggle, byKind],
  )

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useFavorites(): FavoritesValue {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useFavorites precisa estar dentro de <FavoritesProvider>')
  return ctx
}
