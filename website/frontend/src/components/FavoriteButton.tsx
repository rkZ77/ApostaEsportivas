import { Star } from 'lucide-react'
import { motion } from 'framer-motion'
import { useAuth } from '../context/AuthContext'
import { useFavorites, type FavoriteKind } from '../context/FavoritesContext'
import { cn } from '../lib/cn'

/*
 * Botão de favoritar.
 *
 * Estrela e não coração: coração lê como "curtida" e favorito aqui é
 * organização, não reação. O site já tem reação em pick, com outro significado.
 *
 * Some para quem não está logado em vez de aparecer desabilitado: um botão
 * morto num card convida ao clique e não explica nada.
 */
export default function FavoriteButton({
  kind,
  refId,
  label,
  size = 'md',
  className,
}: {
  kind: FavoriteKind
  refId: string | number
  /** Nome legível, guardado junto pra listar favoritos sem novo lookup. */
  label?: string
  size?: 'sm' | 'md'
  className?: string
}) {
  const { user } = useAuth()
  const { isFavorite, toggle } = useFavorites()

  if (!user) return null

  const active = isFavorite(kind, refId)
  const icon = size === 'sm' ? 'w-3.5 h-3.5' : 'w-4 h-4'

  return (
    <motion.button
      type="button"
      whileTap={{ scale: 0.85 }}
      aria-pressed={active}
      aria-label={active ? 'Remover dos favoritos' : 'Adicionar aos favoritos'}
      title={active ? 'Remover dos favoritos' : 'Adicionar aos favoritos'}
      onClick={e => { e.stopPropagation(); toggle(kind, refId, label) }}
      className={cn(
        'inline-flex items-center justify-center shrink-0 rounded-md transition-colors duration-1 ease-smooth',
        size === 'sm' ? 'p-1' : 'p-1.5',
        active ? 'text-yellow-400 hover:text-yellow-300' : 'text-ink-4 hover:text-ink-2',
        className,
      )}
    >
      <Star className={cn(icon, active && 'fill-current')} />
    </motion.button>
  )
}
