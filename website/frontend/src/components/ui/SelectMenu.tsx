import { useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Check, ChevronDown, Search } from 'lucide-react'
import { cn } from '../../lib/cn'

/*
 * Seletor de opção única: um botão com o valor atual, que abre a lista.
 *
 * Substitui as duas coisas que o site usava pra escolher UM valor entre muitos:
 *
 *   - a parede de pills (PillGroup). Escala até uns oito itens; com 24 meses de
 *     histórico ela vira quatro linhas de botões e empurra o conteúdo da tela
 *     pra fora, no celular ainda mais.
 *   - o <select> nativo. Escala, mas a lista é desenhada pelo sistema: fonte,
 *     cor e altura são do Android, não do site, e não cabe ícone, contagem nem
 *     valor por opção.
 *
 * Aqui a lista é do site: rola dentro de uma altura fixa, marca o escolhido,
 * aceita um texto de apoio por linha e ganha busca sozinha quando a lista fica
 * longa. Fecha no clique fora, no Esc e na escolha.
 */

export interface SelectMenuOption {
  value: string
  label: string
  /** Texto de apoio à direita (contagem, lucro, o que a tela quiser). */
  meta?: string
  icon?: React.ReactNode
}

/** A partir daqui a lista ganha campo de busca. Abaixo disso ele só atrapalha. */
const PISO_BUSCA = 12

export default function SelectMenu({
  options, value, onChange,
  placeholder = 'Selecionar',
  className,
  menuClassName,
  align = 'left',
  ariaLabel,
  disabled,
}: {
  options: SelectMenuOption[]
  value: string
  onChange: (v: string) => void
  placeholder?: string
  className?: string
  menuClassName?: string
  align?: 'left' | 'right'
  ariaLabel?: string
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [busca, setBusca] = useState('')
  const raiz = useRef<HTMLDivElement>(null)

  const atual = options.find(o => o.value === value)

  // Fecha no clique fora e no Esc. Sem isso o menu ficava aberto por cima do
  // conteúdo enquanto a pessoa tentava ler o que tinha acabado de filtrar.
  useEffect(() => {
    if (!open) return
    const fora = (e: MouseEvent) => {
      if (raiz.current && !raiz.current.contains(e.target as Node)) setOpen(false)
    }
    const tecla = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', fora)
    document.addEventListener('keydown', tecla)
    return () => {
      document.removeEventListener('mousedown', fora)
      document.removeEventListener('keydown', tecla)
    }
  }, [open])

  useEffect(() => { if (!open) setBusca('') }, [open])

  const comBusca = options.length >= PISO_BUSCA
  const filtradas = useMemo(() => {
    const t = busca.trim().toLowerCase()
    if (!t) return options
    return options.filter(o => o.label.toLowerCase().includes(t))
  }, [options, busca])

  return (
    <div ref={raiz} className={cn('relative inline-block', className)}>
      <button
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        onClick={() => setOpen(o => !o)}
        className={cn(
          'flex items-center gap-2 w-full px-3 py-2 rounded-lg border text-xs font-bold transition-colors',
          'disabled:opacity-40 disabled:cursor-not-allowed',
          open
            ? 'border-accent/40 bg-accent/10 text-accent-ink'
            : 'border-line-strong text-ink-2 hover:border-ink-4',
        )}
      >
        {atual?.icon}
        <span className="truncate flex-1 text-left">{atual?.label ?? placeholder}</span>
        <ChevronDown className={cn('w-3.5 h-3.5 shrink-0 transition-transform', open && 'rotate-180')} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            role="listbox"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.14, ease: [0.16, 1, 0.3, 1] }}
            className={cn(
              'absolute z-50 mt-1.5 min-w-full w-max max-w-[min(88vw,20rem)]',
              'card p-1 border-line-strong shadow-xl',
              align === 'right' ? 'right-0' : 'left-0',
              menuClassName,
            )}
          >
            {comBusca && (
              <div className="flex items-center gap-2 px-2 py-1.5 mb-1 border-b border-line">
                <Search className="w-3.5 h-3.5 text-ink-4 shrink-0" />
                <input
                  autoFocus
                  value={busca}
                  onChange={e => setBusca(e.target.value)}
                  placeholder="Buscar"
                  className="bg-transparent outline-none text-xs text-ink-1 placeholder:text-ink-4 w-full"
                />
              </div>
            )}

            <div className="max-h-64 overflow-y-auto">
              {filtradas.length === 0 && (
                <p className="px-3 py-3 text-xs text-ink-4">Nada encontrado.</p>
              )}
              {filtradas.map(o => {
                const sel = o.value === value
                return (
                  <button
                    key={o.value || '__vazio'}
                    type="button"
                    role="option"
                    aria-selected={sel}
                    onClick={() => { onChange(o.value); setOpen(false) }}
                    className={cn(
                      'flex items-center gap-2 w-full px-2.5 py-2 rounded-md text-left transition-colors',
                      sel ? 'bg-accent/10 text-accent-ink' : 'text-ink-2 hover:bg-surface-1',
                    )}
                  >
                    <Check className={cn('w-3.5 h-3.5 shrink-0', sel ? 'opacity-100' : 'opacity-0')} />
                    {o.icon}
                    <span className="text-xs font-semibold truncate flex-1">{o.label}</span>
                    {o.meta && (
                      <span className="font-mono text-[10px] text-ink-4 tabular-nums shrink-0">{o.meta}</span>
                    )}
                  </button>
                )
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
