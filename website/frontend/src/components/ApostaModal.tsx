import { useState } from 'react'

const HOUSES = ['Superbet', 'Bet365', 'Betano', 'Outra']

interface Props {
  pickOdd: number
  suggestedUnits?: number
  suggestedHouse?: string
  onConfirm: (actualOdd: number, betHouse: string, stakeUnits: number) => void
  onCancel: () => void
  loading?: boolean
  error?: string | null
}

export default function ApostaModal({
  pickOdd, suggestedUnits = 1, suggestedHouse, onConfirm, onCancel, loading, error
}: Props) {
  const [oddStr, setOddStr] = useState(String(pickOdd))
  const [house,  setHouse]  = useState(suggestedHouse ?? '')
  const [units,  setUnits]  = useState(suggestedUnits)
  const [overrideStep, setOverrideStep] = useState(false)

  const parsed   = parseFloat(oddStr)
  const validOdd = !isNaN(parsed) && parsed >= 1.01 && parsed <= 99
  const oddChanged = validOdd && Math.abs(parsed - pickOdd) > 0.001
  const exceedsMax = units > 10
  const exceedsSuggested = units > suggestedUnits
  const valid = validOdd && house.length > 0 && units >= 1 && !exceedsMax

  function handlePrimary() {
    if (!valid) return
    if (exceedsSuggested && !overrideStep) {
      setOverrideStep(true)
      return
    }
    onConfirm(parsed, house, units)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-xs bg-zinc-900 border border-zinc-700 rounded-2xl overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {overrideStep ? (
          /* ── Tela de confirmação ao exceder sugestão ── */
          <div className="p-5">
            <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-xl p-4 mb-5">
              <p className="text-yellow-400 font-black text-sm mb-1">Stake acima do recomendado</p>
              <p className="text-yellow-200 text-xs leading-relaxed">
                Você está apostando <strong>{units}u</strong> — a IA recomendou <strong>{suggestedUnits}u</strong> para proteger sua banca.
                Apostar mais do que o sugerido pode aumentar o risco de ruína.
              </p>
              <p className="text-yellow-400/70 text-xs mt-2">Tem certeza que quer continuar?</p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setOverrideStep(false)}
                className="flex-1 py-2.5 rounded-xl border border-zinc-700 text-zinc-400 text-sm hover:border-zinc-500 transition-colors"
              >
                Voltar
              </button>
              <button
                onClick={() => onConfirm(parsed, house, units)}
                disabled={loading}
                className="flex-1 py-2.5 rounded-xl bg-yellow-600 hover:bg-yellow-500 disabled:opacity-50 text-white font-bold text-sm transition-colors"
              >
                {loading ? '...' : 'Confirmar mesmo assim'}
              </button>
            </div>
          </div>
        ) : (
          /* ── Tela principal ── */
          <div className="p-5">
            <h3 className="text-white font-black text-sm mb-1">Registrar aposta</h3>
            <p className="text-zinc-500 text-xs mb-4">Informe onde e como você apostou.</p>

            {/* Casa de aposta */}
            <div className="mb-4">
              <label className="text-zinc-400 text-xs font-semibold mb-1.5 block">Casa de aposta</label>
              <div className="grid grid-cols-2 gap-1.5">
                {HOUSES.map(h => (
                  <button
                    key={h}
                    type="button"
                    onClick={() => setHouse(h)}
                    className={`py-2 rounded-xl border text-xs font-bold transition-colors ${
                      house === h
                        ? 'border-green-500/60 bg-green-500/10 text-green-400'
                        : 'border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200'
                    }`}
                  >
                    {h}
                  </button>
                ))}
              </div>
            </div>

            {/* Odd */}
            <div className="mb-4">
              <label className="text-zinc-400 text-xs font-semibold mb-1.5 block">
                Odd apostada
                <span className="text-zinc-600 font-normal ml-1">(pick: {pickOdd})</span>
              </label>
              <input
                type="number" step="0.01" min="1.01" value={oddStr}
                onChange={e => setOddStr(e.target.value)}
                className="input w-full text-center text-xl font-black"
              />
              {oddChanged && (
                <p className="text-yellow-400 text-[11px] mt-1.5">
                  Odd diferente do pick — será registrada como apostada
                </p>
              )}
            </div>

            {/* Unidades */}
            <div className="mb-4">
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-zinc-400 text-xs font-semibold">Unidades a apostar</label>
                <span className="text-[10px] text-zinc-600">IA sugere: <span className="text-green-400 font-bold">{suggestedUnits}u</span></span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setUnits(u => Math.max(1, u - 1))}
                  className="w-9 h-9 rounded-xl border border-zinc-700 text-zinc-300 text-lg font-bold hover:border-zinc-500 transition-colors flex items-center justify-center"
                >−</button>
                <input
                  type="number" min="1" max="10" step="1" value={units}
                  onChange={e => setUnits(Math.max(1, Math.min(10, parseInt(e.target.value) || 1)))}
                  className="input flex-1 text-center text-xl font-black"
                />
                <button
                  type="button"
                  onClick={() => setUnits(u => Math.min(10, u + 1))}
                  className="w-9 h-9 rounded-xl border border-zinc-700 text-zinc-300 text-lg font-bold hover:border-zinc-500 transition-colors flex items-center justify-center"
                >+</button>
              </div>
              {exceedsSuggested && !exceedsMax && (
                <p className="text-yellow-400 text-[11px] mt-1.5">
                  Acima da sugestão — você será solicitado a confirmar
                </p>
              )}
              {exceedsMax && (
                <p className="text-red-400 text-[11px] mt-1.5">Máximo 10 unidades por aposta</p>
              )}
            </div>

            {error && (
              <p className="text-red-400 text-xs mb-3 text-center">{error}</p>
            )}

            <div className="flex gap-2">
              <button
                onClick={onCancel}
                className="flex-1 py-2.5 rounded-xl border border-zinc-700 text-zinc-400 text-sm hover:border-zinc-500 transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={handlePrimary}
                disabled={!valid || loading}
                className={`flex-1 py-2.5 rounded-xl font-bold text-sm transition-colors disabled:opacity-50 ${
                  exceedsSuggested
                    ? 'bg-yellow-600 hover:bg-yellow-500 text-white'
                    : 'bg-green-600 hover:bg-green-500 text-white'
                }`}
              >
                {loading ? '...' : exceedsSuggested ? `Apostar ${units}u →` : 'Registrar aposta'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
