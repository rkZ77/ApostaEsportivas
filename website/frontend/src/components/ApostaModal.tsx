import { useState } from 'react'

const HOUSES = ['Superbet', 'Bet365', 'Betano', 'Outra']

interface Props {
  pickOdd: number
  onConfirm: (actualOdd: number, betHouse: string) => void
  onCancel: () => void
  loading?: boolean
}

export default function ApostaModal({ pickOdd, onConfirm, onCancel, loading }: Props) {
  const [oddStr, setOddStr]     = useState(String(pickOdd))
  const [house, setHouse]       = useState('')
  const [customHouse, setCustomHouse] = useState('')

  const parsed = parseFloat(oddStr)
  const validOdd = !isNaN(parsed) && parsed >= 1.01 && parsed <= 99
  const changed  = validOdd && Math.abs(parsed - pickOdd) > 0.001
  const finalHouse = house === 'Outra' ? customHouse.trim() : house
  const valid = validOdd && finalHouse.length > 0

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
          Informe onde e com qual odd você apostou.
        </p>

        {/* Casa de aposta */}
        <div className="mb-4">
          <label className="text-zinc-400 text-xs font-semibold mb-1.5 block">Casa de aposta</label>
          <div className="grid grid-cols-2 gap-1.5">
            {HOUSES.map(h => (
              <button
                key={h}
                type="button"
                onClick={() => { setHouse(h); if (h !== 'Outra') setCustomHouse('') }}
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
          {house === 'Outra' && (
            <input
              type="text"
              placeholder="Nome da casa..."
              value={customHouse}
              onChange={e => setCustomHouse(e.target.value)}
              className="input w-full text-sm mt-2"
              autoFocus
            />
          )}
        </div>

        {/* Odd */}
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
            onClick={() => valid && onConfirm(parsed, finalHouse)}
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
