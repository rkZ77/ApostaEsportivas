import { useState } from 'react'
import { SlidersHorizontal, X, ChevronDown } from 'lucide-react'

export interface FilterOption { value: string; label: string; icon?: React.ReactNode }
export interface FilterGroup {
  key: string
  label: string
  options: FilterOption[]
  value: string
  onChange: (value: string) => void
  /** Valor "neutro" do grupo (ex: "Todos") -- default: primeira opcao. So mostra
   * chip/contador quando o valor atual difere disso. */
  defaultValue?: string
}

const ACCENTS: Record<string, { chip: string; active: string; badge: string }> = {
  green:  { chip: 'border-green-500/40 text-green-400 bg-green-500/10',   active: 'bg-green-500/15 border-green-500/40 text-green-400',   badge: 'bg-green-500 text-black' },
  yellow: { chip: 'border-yellow-400/40 text-yellow-400 bg-yellow-400/10', active: 'bg-yellow-400/15 border-yellow-400/40 text-yellow-400', badge: 'bg-yellow-400 text-black' },
  blue:   { chip: 'border-blue-400/40 text-blue-400 bg-blue-400/10',       active: 'bg-blue-400/15 border-blue-400/40 text-blue-400',       badge: 'bg-blue-400 text-black' },
}

export default function FilterPanel({
  groups, accent = 'green', extra, extraWhen,
}: {
  groups: FilterGroup[]
  accent?: 'green' | 'yellow' | 'blue'
  /** Conteudo extra dentro do painel aberto (ex: datepicker de periodo custom) */
  extra?: React.ReactNode
  /** So renderiza `extra` quando essa condicao for verdadeira (ex: periodo === 'custom') */
  extraWhen?: boolean
}) {
  const [open, setOpen] = useState(false)
  const c = ACCENTS[accent]

  const neutral = (g: FilterGroup) => g.defaultValue ?? g.options[0]?.value ?? ''

  // "Ativo" = valor diferente do neutro do grupo (ex: "Todos"). Fonte/Periodo
  // sempre tem algo selecionado, entao nao da pra usar "vazio" como sinal de
  // inativo -- cada grupo declara (ou herda da 1a opcao) o que conta como neutro.
  const activeChips = groups
    .filter(g => g.value !== neutral(g))
    .map(g => ({ key: g.key, label: g.options.find(o => o.value === g.value)?.label ?? g.value, onClear: () => g.onChange(neutral(g)) }))

  const clearAll = () => groups.forEach(g => { if (g.value !== neutral(g)) g.onChange(neutral(g)) })

  return (
    <div className="mb-5">
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => setOpen(o => !o)}
          className={`flex items-center gap-1.5 text-xs font-bold px-3 py-2 rounded-lg border transition-colors ${open ? c.active : 'border-zinc-700 text-zinc-300 hover:border-zinc-500'}`}
        >
          <SlidersHorizontal className="w-3.5 h-3.5" />
          Filtros
          {activeChips.length > 0 && (
            <span className={`inline-flex items-center justify-center w-4 h-4 rounded-full text-[10px] font-black ${c.badge}`}>
              {activeChips.length}
            </span>
          )}
          <ChevronDown className={`w-3.5 h-3.5 transition-transform ${open ? 'rotate-180' : ''}`} />
        </button>

        {!open && activeChips.map(chip => (
          <span key={chip.key} className={`flex items-center gap-1 text-[11px] font-semibold px-2.5 py-1.5 rounded-lg border ${c.chip}`}>
            {chip.label}
            <button onClick={chip.onClear} className="hover:opacity-70" aria-label={`Remover filtro ${chip.label}`}>
              <X className="w-3 h-3" />
            </button>
          </span>
        ))}
      </div>

      {open && (
        <div className="mt-2 card p-4 space-y-4 border-zinc-800">
          {groups.map(g => (
            <div key={g.key}>
              <p className="text-xs text-zinc-500 uppercase mb-2">{g.label}</p>
              {/* Muitas opcoes (ex: 30 meses de historico) viram select nativo em
                  vez de parede de botoes -- pill buttons soh escalam bem ate uns
                  8 itens, depois disso o painel fica maior que a tela. */}
              {g.options.length > 8 ? (
                <select
                  value={g.value}
                  onChange={e => g.onChange(e.target.value)}
                  className="input text-sm py-2 w-full"
                >
                  {g.options.map(opt => (
                    <option key={opt.value || 'all'} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {g.options.map(opt => (
                    <button
                      key={opt.value || 'all'}
                      onClick={() => g.onChange(opt.value)}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${g.value === opt.value ? c.active : 'border-zinc-700 text-zinc-400 hover:border-zinc-500'}`}
                    >
                      {opt.icon}
                      {opt.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}

          {extra && extraWhen !== false && extra}

          <div className="flex items-center justify-between pt-1 border-t border-zinc-800">
            <button
              onClick={clearAll}
              disabled={activeChips.length === 0}
              className="text-xs font-semibold text-zinc-500 hover:text-zinc-300 disabled:opacity-30 transition-colors"
            >
              Limpar filtros
            </button>
            <button
              onClick={() => setOpen(false)}
              className={`text-xs font-bold px-4 py-2 rounded-lg border ${c.active}`}
            >
              Aplicar
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
