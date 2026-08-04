import { Info } from 'lucide-react'
import Tooltip from './ui/Tooltip'

/**
 * Ícone de informação que abre uma explicação curta.
 * A mecânica (portal, posicionamento, fechar no scroll) vive em ui/Tooltip:
 * aqui fica só o gatilho padrão de "o que significa isso".
 */
export default function InfoTip({ text, className = '' }: { text: string; className?: string }) {
  return (
    <Tooltip text={text} className={className}>
      <button
        type="button"
        aria-label="O que significa"
        className="text-ink-4 hover:text-ink-2 transition-colors shrink-0"
      >
        <Info className="w-3.5 h-3.5" />
      </button>
    </Tooltip>
  )
}
