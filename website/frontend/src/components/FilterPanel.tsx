import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { SlidersHorizontal, X, ChevronDown } from 'lucide-react'
import { SearchInput } from './ui'

export interface FilterOption { value: string; label: string; icon?: React.ReactNode }

/**
 * Busca por texto. Opcional, mas quando existe fica FORA do painel dobrável.
 *
 * Busca não é recorte, é atalho: quem digita "Palmeiras" quer o resultado
 * enquanto digita, não depois de abrir um painel. Era o que a aba Mercados
 * fazia com controles próprios, e o motivo de ela parecer outra ferramenta.
 */
export interface FilterSearch {
  value: string
  onChange: (v: string) => void
  placeholder?: string
}

/** Ordenação. Fica dentro do painel: é escolha rara, e são poucas opções. */
export interface FilterSort {
  label?: string
  options: FilterOption[]
  value: string
  onChange: (v: string) => void
  /**
   * Ordem "natural" da lista · default: primeira opção.
   *
   * Existe pelo mesmo motivo que `defaultValue` nos grupos: com o painel
   * fechado, uma lista reordenada ficava indistinguível de uma lista normal.
   * Quem escolheu "maior odd" e voltou dez minutos depois via os picks fora da
   * ordem do motor sem nada na tela explicando por quê.
   */
  defaultValue?: string
}
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
  yellow: { chip: 'border-yellow-400/40 text-yellow-400 bg-yellow-400/10', active: 'bg-yellow-400/15 border-yellow-400/40 text-yellow-400', badge: 'bg-yellow-400 text-on-fill' },
  blue:   { chip: 'border-blue-400/40 text-blue-400 bg-blue-400/10',       active: 'bg-blue-400/15 border-blue-400/40 text-blue-400',       badge: 'bg-blue-400 text-on-fill' },
}

export default function FilterPanel({
  groups, accent = 'green', extra, extraWhen, resultado, busca, ordem,
}: {
  groups: FilterGroup[]
  busca?: FilterSearch
  ordem?: FilterSort
  accent?: 'green' | 'yellow' | 'blue'
  /** Conteudo extra dentro do painel aberto (ex: datepicker de periodo custom) */
  extra?: React.ReactNode
  /** So renderiza `extra` quando essa condicao for verdadeira (ex: periodo === 'custom') */
  extraWhen?: boolean
  /**
   * Quantos itens sobraram depois do filtro.
   *
   * Sem isto o painel nunca respondia a pergunta que o usuario tem ao filtrar:
   * "sobrou alguma coisa?". Ele fechava e o resultado so' aparecia depois de
   * rolar a pagina -- e uma lista vazia por filtro apertado fica igualzinha a
   * uma lista vazia por nao existir dado. So' a aba Mercados mostrava isso.
   */
  resultado?: number
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

  const ordemNeutra = ordem ? (ordem.defaultValue ?? ordem.options[0]?.value ?? '') : ''
  const ordemAtiva = ordem && ordem.value !== ordemNeutra
    ? [{
        key: '__ordem',
        label: ordem.options.find(o => o.value === ordem.value)?.label ?? ordem.value,
        onClear: () => ordem.onChange(ordemNeutra),
      }]
    : []

  // A busca entra no rastro de chips: digitada e painel fechado, ela some da
  // vista e o usuario fica sem entender por que a lista esta curta.
  const chips = [
    ...(busca?.value.trim()
      ? [{ key: '__busca', label: `"${busca.value.trim()}"`, onClear: () => busca.onChange('') }]
      : []),
    ...activeChips,
    ...ordemAtiva,
  ]

  const clearAll = () => {
    groups.forEach(g => { if (g.value !== neutral(g)) g.onChange(neutral(g)) })
    if (ordem && ordem.value !== ordemNeutra) ordem.onChange(ordemNeutra)
    busca?.onChange('')
  }

  return (
    <div className="mb-5">
      {busca && (
        <SearchInput
          value={busca.value}
          onChange={busca.onChange}
          placeholder={busca.placeholder ?? 'Buscar'}
          className="mb-3"
        />
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => setOpen(o => !o)}
          className={`flex items-center gap-1.5 text-xs font-bold px-3 py-2 rounded-lg border transition-colors ${open ? c.active : 'border-line-strong text-ink-2 hover:border-ink-4'}`}
        >
          <SlidersHorizontal className="w-3.5 h-3.5" />
          Filtros
          {chips.length > 0 && (
            <span className={`inline-flex items-center justify-center w-4 h-4 rounded-full text-[10px] font-black ${c.badge}`}>
              {chips.length}
            </span>
          )}
          <ChevronDown className={`w-3.5 h-3.5 transition-transform ${open ? 'rotate-180' : ''}`} />
        </button>

        {!open && chips.length > 0 && resultado != null && (
          <span className={`text-[11px] font-semibold px-2.5 py-1.5 rounded-lg border ${resultado > 0 ? c.chip : 'border-line-strong text-ink-4'}`}>
            {resultado === 1 ? '1 resultado' : `${resultado} resultados`}
          </span>
        )}

        {!open && chips.map(chip => (
          <motion.span
            key={chip.key}
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            className={`flex items-center gap-1 text-[11px] font-semibold px-2.5 py-1.5 rounded-lg border ${c.chip}`}
          >
            {chip.label}
            <button onClick={chip.onClear} className="hover:opacity-70" aria-label={`Remover filtro ${chip.label}`}>
              <X className="w-3 h-3" />
            </button>
          </motion.span>
        ))}

        {/* Limpar tudo SEM abrir o painel. Com três chips na tela, voltar à
            lista inteira custava abrir o painel e caçar o "Limpar filtros" lá
            dentro · ou tirar chip por chip. */}
        {!open && chips.length > 1 && (
          <button
            onClick={clearAll}
            className="text-[11px] font-semibold text-ink-3 hover:text-ink-1 px-2.5 py-1.5 rounded-lg border border-line-strong hover:border-ink-4 transition-colors"
          >
            Limpar tudo
          </button>
        )}
      </div>

      <AnimatePresence initial={false}>
      {open && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          exit={{ opacity: 0, height: 0 }}
          transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
          className="overflow-hidden"
        >
        <div className="mt-2 card p-4 space-y-4 border-line">
          {groups.map(g => (
            <div key={g.key}>
              <p className="text-xs text-ink-3 mb-2">{g.label}</p>
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
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${g.value === opt.value ? c.active : 'border-line-strong text-ink-2 hover:border-ink-4'}`}
                    >
                      {opt.icon}
                      {opt.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}

          {ordem && (
            <div>
              <p className="text-xs text-ink-3 mb-2">{ordem.label ?? 'Ordenar por'}</p>
              <div className="flex flex-wrap gap-2">
                {ordem.options.map(opt => (
                  <button
                    key={opt.value}
                    onClick={() => ordem.onChange(opt.value)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${ordem.value === opt.value ? c.active : 'border-line-strong text-ink-2 hover:border-ink-4'}`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {extra && extraWhen !== false && extra}

          <div className="flex items-center justify-between pt-1 border-t border-line">
            <button
              onClick={clearAll}
              disabled={chips.length === 0}
              className="text-xs font-semibold text-ink-3 hover:text-ink-2 disabled:opacity-30 transition-colors"
            >
              Limpar filtros
            </button>
            {/*
              Dizia "Aplicar" e nao aplicava nada: cada opcao ja chama onChange
              no clique, entao o botao so' fechava o painel. O rotulo prometia
              um estado pendente que nunca existiu -- quem clicava numa opcao e
              saia sem apertar aqui achava que tinha perdido a escolha.

              Agora ele diz o que faz e, de quebra, entrega o numero: fechar o
              painel e ver os N que sobraram e' a mesma acao.
            */}
            <button
              onClick={() => setOpen(false)}
              className={`text-xs font-bold px-4 py-2 rounded-lg border ${c.active}`}
            >
              {resultado == null
                ? 'Fechar'
                : resultado === 1 ? 'Ver 1 resultado' : `Ver ${resultado} resultados`}
            </button>
          </div>
        </div>
        </motion.div>
      )}
      </AnimatePresence>
    </div>
  )
}
