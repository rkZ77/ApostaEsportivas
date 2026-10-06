import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'

/*
 * Voltar · discreto de propósito (2026-10-06).
 *
 * Era um círculo de 44px com borda, do tamanho de um botão de ação e mais
 * pesado que o próprio título da página ao lado. Agora é um ícone com área de
 * toque de 36px e fundo só no hover/foco: continua fácil de acertar com o
 * dedo e deixa de competir com o que a página tem a dizer.
 */
export default function BackButton({ to, className = '' }: { to?: string; className?: string }) {
  const navigate = useNavigate()
  return (
    <motion.button
      type="button"
      whileTap={{ scale: 0.9 }}
      onClick={() => (to ? navigate(to) : navigate(-1))}
      aria-label="Voltar"
      className={`flex items-center justify-center w-9 h-9 rounded-lg text-ink-3 hover:text-ink-1 hover:bg-surface-2 focus-visible:bg-surface-2 transition-colors shrink-0 ${className}`}
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round">
        <path d="M15 18l-6-6 6-6" />
      </svg>
    </motion.button>
  )
}
