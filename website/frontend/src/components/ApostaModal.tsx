import { useState } from 'react'

interface Props {
  pickOdd: number
  onConfirm: (actualOdd: number) => void
  onCancel: () => void
  loading?: boolean
}

export default function ApostaModal({ pickOdd, onConfirm, onCancel, loading }: Props) {
  const [oddStr, setOddStr] = useState(String(pickOdd))
  const parsed = parseFloat(oddStr)
  const valid = !isNaN(parsed) && parsed >= 1.01 && parsed <= 99
  const changed = valid && Math.abs(parsed - pickOdd) > 0.001

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-xs bg-zinc-900 border border-zinc-700 rounded-2xl p-5"
        onClick={e => e.stopPropagation()}
      >
        <h3 className="text-white font-black text-sm mb-1">Confirmar aposta</h3>
        <p className="text-zinc-500 text-xs mb-4">
          Confirme a odd que você conseguiu na casa de apostas.
        </p>

        <div className="mb-4">
          <label className="text-zinc-400 text-xs font-semibold mb-1.5 block">
            Odd apostada
            <span className="text-zinc-600 font-normal ml-1">(pick: {pickOdd})</span>
          </label>
          <input
            type="number"
            step="0.01"
            min="1.01"
            value={oddStr}
            onChange={e => setOddStr(e.target.value)}
            className="input w-full text-center text-xl font-black"
            autoFocus
          />
          {changed && (
            <p className="text-yellow-400 text-[11px] mt-1.5">
              Odd diferente do pick: será registrada como apostada
            </p>
          )}
        </div>

        <div className="flex gap-2">
          <button
            onClick={onCancel}
            className="flex-1 py-2.5 rounded-xl border border-zinc-700 text-zinc-400 text-sm hover:border-zinc-500 transition-colors"
          >
            Cancelar
          </button>
          <button
            onClick={() => valid && onConfirm(parsed)}
            disabled={!valid || loading}
            className="flex-1 py-2.5 rounded-xl bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white font-bold text-sm transition-colors"
          >
            {loading ? '…' : 'Apostei'}
          </button>
        </div>
      </div>
    </div>
  )
}
