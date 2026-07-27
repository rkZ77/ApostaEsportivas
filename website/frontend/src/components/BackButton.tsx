import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'

export default function BackButton({ to, className = '' }: { to?: string; className?: string }) {
  const navigate = useNavigate()
  return (
    <motion.button
      whileTap={{ scale: 0.9 }}
      onClick={() => (to ? navigate(to) : navigate(-1))}
      aria-label="Voltar"
      className={`flex items-center justify-center w-11 h-11 rounded-full border border-zinc-800 text-zinc-500 hover:border-zinc-600 hover:text-white transition-colors shrink-0 ${className}`}
    >
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M15 18l-6-6 6-6" />
      </svg>
    </motion.button>
  )
}
