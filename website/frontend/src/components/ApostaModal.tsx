import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { backdropFade, sheetUp, tabFade } from '../lib/motion'

const HOUSES = ['Superbet', 'Bet365', 'Betano', 'Outra']

interface Props {
  /** Odd que abre o campo · já é a atualizada quando a consulta trouxe uma. */
  pickOdd: number
  /**
   * Odd publicada no pick, quando ela for diferente da que abre o campo.
   * Sem isso o rótulo "(pick: X)" passaria a mostrar a odd nova como se fosse
   * a do pick, e a mudança que acabou de acontecer ficaria invisível.
   */
  originalOdd?: number
  suggestedUnits?: number
  suggestedHouse?: string
  maxUnits?: number
  hideUnits?: boolean
  onConfirm: (actualOdd: number, betHouse: string, stakeUnits: number) => void
  onCancel: () => void
  loading?: boolean
  error?: string | null
}

export default function ApostaModal({
  pickOdd, originalOdd, suggestedUnits = 1, suggestedHouse, maxUnits = 10, hideUnits = false,
  onConfirm, onCancel, loading, error
}: Props) {
  const [oddStr, setOddStr] = useState(String(pickOdd))
  const [house,  setHouse]  = useState(suggestedHouse ?? '')
  const [units,  setUnits]  = useState(suggestedUnits)
  const [overrideStep, setOverrideStep] = useState(false)

  const parsed   = parseFloat(oddStr)
  const validOdd = !isNaN(parsed) && parsed >= 1.01 && parsed <= 99
  const oddChanged = validOdd && Math.abs(parsed - pickOdd) > 0.001
  // Movimento entre a odd publicada e a de agora · subiu, caiu ou nada.
  const oddPick = originalOdd ?? pickOdd
  const variacao = Math.abs(pickOdd - oddPick) > 0.001 ? pickOdd - oddPick : 0
  const exceedsMax = !hideUnits && units > maxUnits
  const exceedsSuggested = !hideUnits && units > suggestedUnits
  const valid = validOdd && house.length > 0 && (hideUnits || (units >= 1 && !exceedsMax))

  function handlePrimary() {
    if (!valid) return
    if (exceedsSuggested && !overrideStep) {
      setOverrideStep(true)
      return
    }
    onConfirm(parsed, house, units)
  }

  return (
    <motion.div
      variants={backdropFade}
      initial="hidden"
      animate="visible"
      exit="exit"
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
      onClick={onCancel}
    >
      <motion.div
        variants={sheetUp}
        className="w-full max-w-xs bg-surface-1 border border-line-strong rounded-lg overflow-y-auto max-h-[92dvh]"
        onClick={e => e.stopPropagation()}
      >
        <AnimatePresence mode="wait">
        {overrideStep ? (
          /* ── Tela de confirmação ao exceder sugestão ── */
          <motion.div key="override" variants={tabFade} initial="hidden" animate="visible" exit="exit" className="p-5">
            <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-md p-4 mb-5">
              <p className="text-yellow-400 font-black text-sm mb-1">Stake acima do recomendado</p>
              <p className="text-yellow-200 text-xs leading-relaxed">
                Você está apostando <strong>{units}u</strong>, a IA recomendou <strong>{suggestedUnits}u</strong> para proteger sua banca.
                Apostar mais do que o sugerido pode aumentar o risco de ruína.
              </p>
              <p className="text-yellow-400/70 text-xs mt-2">Tem certeza que quer continuar?</p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setOverrideStep(false)}
                className="flex-1 py-2.5 rounded-md border border-line-strong text-ink-2 text-sm hover:border-ink-4 transition-colors"
              >
                Voltar
              </button>
              <button
                onClick={() => onConfirm(parsed, house, units)}
                disabled={loading}
                className="flex-1 py-2.5 rounded-md bg-yellow-600 hover:bg-yellow-500 disabled:opacity-50 text-ink-1 font-bold text-sm transition-colors"
              >
                {loading ? '...' : 'Estou ciente'}
              </button>
            </div>
          </motion.div>
        ) : (
          /* ── Tela principal ── */
          <motion.div key="main" variants={tabFade} initial="hidden" animate="visible" exit="exit" className="p-5">
            <h3 className="text-ink-1 font-bold text-sm mb-1">Registrar aposta</h3>
            <p className="text-ink-3 text-xs mb-4">Informe onde e como você apostou.</p>

            {/* Casa de aposta */}
            <div className="mb-4">
              <label className="text-ink-2 text-xs font-semibold mb-1.5 block">Casa de aposta</label>
              <div className="grid grid-cols-2 gap-1.5">
                {HOUSES.map(h => (
                  <button
                    key={h}
                    type="button"
                    onClick={() => setHouse(h)}
                    className={`py-2 rounded-md border text-xs font-bold transition-colors ${
                      house === h
                        ? 'border-green-500/60 bg-green-500/10 text-green-400'
                        : 'border-line-strong text-ink-2 hover:border-ink-4 hover:text-ink-2'
                    }`}
                  >
                    {h}
                  </button>
                ))}
              </div>
            </div>

            {/* Odd */}
            <div className="mb-4">
              <label className="text-ink-2 text-xs font-semibold mb-1.5 block">
                Odd apostada
                <span className="text-ink-4 font-normal ml-1">(pick: {oddPick})</span>
              </label>
              <input
                type="number" step="0.01" min="1.01" value={oddStr}
                onChange={e => setOddStr(e.target.value)}
                className="input font-mono w-full text-center text-xl font-black"
              />
              {/* Movimento da casa desde a publicação do pick. Aparece nos dois
                  sentidos: odd que subiu é boa notícia e some se não for dita. */}
              {variacao !== 0 && (
                <p className={`text-[11px] mt-1.5 ${variacao > 0 ? 'text-green-400' : 'text-yellow-400'}`}>
                  Odd atualizada agora, {variacao > 0 ? 'subiu' : 'caiu'} de {oddPick.toFixed(2)} para {pickOdd.toFixed(2)}
                </p>
              )}
              {oddChanged && (
                <p className="text-yellow-400 text-[11px] mt-1.5">
                  Odd diferente do pick, será registrada como apostada
                </p>
              )}
            </div>

            {/* Unidades */}
            {!hideUnits && (
              <div className="mb-4">
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-ink-2 text-xs font-semibold">Unidades a apostar</label>
                  <span className="text-[10px] text-ink-4">IA sugere: <span className="text-green-400 font-bold">{suggestedUnits}u</span></span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setUnits(u => Math.max(1, u - 1))}
                    aria-label="Diminuir unidades"
                    className="w-11 h-11 rounded-md border border-line-strong text-ink-2 text-lg font-bold hover:border-ink-4 transition-colors flex items-center justify-center shrink-0"
                  >−</button>
                  <input
                    type="number" min="1" max={maxUnits} step="1" value={units}
                    onChange={e => setUnits(Math.max(1, Math.min(maxUnits, parseInt(e.target.value) || 1)))}
                    className="input font-mono flex-1 text-center text-xl font-black"
                  />
                  <button
                    type="button"
                    onClick={() => setUnits(u => Math.min(maxUnits, u + 1))}
                    aria-label="Aumentar unidades"
                    className="w-11 h-11 rounded-md border border-line-strong text-ink-2 text-lg font-bold hover:border-ink-4 transition-colors flex items-center justify-center shrink-0"
                  >+</button>
                </div>
                {exceedsSuggested && !exceedsMax && (
                  <p className="text-yellow-400 text-[11px] mt-1.5">
                    Acima da sugestão, você será solicitado a confirmar
                  </p>
                )}
                {exceedsMax && (
                  <p className="text-red-400 text-[11px] mt-1.5">Máximo {maxUnits} unidades por aposta</p>
                )}
              </div>
            )}

            {error && (
              <p className="text-red-400 text-xs mb-3 text-center">{error}</p>
            )}

            <div className="flex gap-2">
              <button
                onClick={onCancel}
                className="flex-1 py-2.5 rounded-md border border-line-strong text-ink-2 text-sm hover:border-ink-4 transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={handlePrimary}
                disabled={!valid || loading}
                className={`flex-1 py-2.5 rounded-md font-bold text-sm transition-colors disabled:opacity-50 ${
                  exceedsSuggested
                    ? 'bg-yellow-600 hover:bg-yellow-500 text-ink-1'
                    : 'bg-green-600 hover:bg-green-500 text-white'
                }`}
              >
                {loading ? '...' : exceedsSuggested ? `Apostar ${units}u` : 'Registrar aposta'}
              </button>
            </div>
          </motion.div>
        )}
        </AnimatePresence>
      </motion.div>
    </motion.div>
  )
}
