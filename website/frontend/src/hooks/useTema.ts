import { useSyncExternalStore } from 'react'
import { getTema, inscrever, type Tema } from '../lib/theme'

/*
 * Le o tema atual e re-renderiza quando ele muda.
 *
 * O terceiro argumento (snapshot do servidor) existe pro caso de o componente
 * ser renderizado fora do navegador: sem ele o React lanca em SSR/prerender.
 */
export function useTema(): Tema {
  return useSyncExternalStore(inscrever, getTema, () => 'dark' as Tema)
}
