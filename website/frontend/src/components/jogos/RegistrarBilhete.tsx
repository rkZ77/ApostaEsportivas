import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, Wallet } from 'lucide-react'
import api from '../../services/api'
import { cn } from '../../lib/cn'
import { limpar, oddCombinada, registraveis, type Selecao } from '../../lib/bilheteMontado'
import { REGISTRO_MAX_UNIDADES } from '../ApostaModal'

/*
 * Registrar o bilhete montado na banca (2026-10-06, pedido do usuário).
 *
 * Vira uma aposta como as do motor: entra no saldo, em Meus Picks e no
 * fechamento do mês, e se liquida sozinho perna a perna quando os jogos
 * terminam (ver backend/bilhete_pessoal.py). Fica fora do histórico público
 * da IA · é a aposta da pessoa, não um pick do Pick IA.
 *
 * A odd é a que a CASA mostrou pro bilhete inteiro: o site não sabe o preço de
 * cada seleção, e é essa a odd que paga.
 */
interface Banca { has_banca: boolean; unit_value: number; bankroll_current: number }

const numeroBr = (v: string) => Number(v.replace(',', '.'))

export default function RegistrarBilhete({ selecoes, onFechar }: {
  selecoes: Selecao[]
  onFechar: () => void
}) {
  const validas = registraveis(selecoes)
  const antigas = selecoes.length - validas.length
  const [banca, setBanca] = useState<Banca | null>(null)
  const [stake, setStake] = useState('1')
  /* Vem sugerida pelo produto das odds das casas quando todas as seleções têm
     odd; a pessoa confirma ou troca pelo número que a casa mostrou. */
  const [odd, setOdd] = useState(() => {
    const o = oddCombinada(registraveis(selecoes))
    return o ? o.toFixed(2).replace('.', ',') : ''
  })
  const [casa, setCasa] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const [feito, setFeito] = useState(false)

  useEffect(() => {
    api.get('/banca/summary').then(r => setBanca(r.data)).catch(() => setBanca(null))
  }, [])

  const unidades = numeroBr(stake)
  const oddNum = numeroBr(odd)
  const valido = validas.length > 0 && unidades >= 0.5 && unidades <= REGISTRO_MAX_UNIDADES && oddNum >= 1.01
  const reais = banca?.unit_value ? unidades * banca.unit_value : null

  const registrar = async () => {
    if (!valido) return
    setEnviando(true)
    setErro(null)
    try {
      await api.post('/banca/bilhete-pessoal', {
        pernas: validas.map(s => s.perna),
        stake_units: unidades,
        actual_odd: oddNum,
        bet_house: casa.trim() || null,
      })
      limpar()
      setFeito(true)
    } catch (e: any) {
      setErro(e?.response?.data?.detail ?? 'Não deu pra registrar agora. Tente de novo.')
    } finally {
      setEnviando(false)
    }
  }

  if (feito) {
    return (
      <div className="px-4 py-8 text-center">
        <CheckCircle2 className="mx-auto text-accent-ink mb-3" size={40} />
        <div className="text-lg font-bold text-ink-1">Bilhete registrado na banca</div>
        <p className="text-sm text-ink-2 mt-2">
          Ele se resolve sozinho, seleção por seleção, quando os jogos terminarem.
        </p>
        <Link to="/meus-picks" onClick={onFechar}
          className="mt-5 inline-flex h-12 items-center px-6 rounded-lg bg-accent text-on-fill font-bold">
          Ver em Meus Picks
        </Link>
      </div>
    )
  }

  if (banca && !banca.has_banca) {
    return (
      <div className="px-4 py-8 text-center">
        <Wallet className="mx-auto text-ink-3 mb-3" size={36} />
        <div className="font-bold text-ink-1">Configure sua banca primeiro</div>
        <p className="text-sm text-ink-2 mt-2">É ela que diz quanto vale uma unidade.</p>
        <Link to="/banca" onClick={onFechar}
          className="mt-5 inline-flex h-12 items-center px-6 rounded-lg bg-accent text-on-fill font-bold">
          Configurar banca
        </Link>
      </div>
    )
  }

  const campo = 'w-full h-12 px-3 rounded-lg bg-surface-1 border border-line text-ink-1 text-base font-mono tabular-nums focus:border-accent outline-none'
  return (
    <div className="px-4 py-4 space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <label className="block">
          <span className="text-xs font-semibold text-ink-2">Stake (unidades)</span>
          <input inputMode="decimal" value={stake} onChange={e => setStake(e.target.value)} className={cn(campo, 'mt-1')} />
          <span className="text-[11px] text-ink-3 mt-1 block tabular-nums">
            {reais != null && Number.isFinite(reais) ? `R$ ${reais.toFixed(2).replace('.', ',')}` : ' '}
          </span>
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-ink-2">Odd do bilhete</span>
          <input inputMode="decimal" placeholder="ex: 3,40" value={odd} onChange={e => setOdd(e.target.value)}
            className={cn(campo, 'mt-1')} />
          <span className="text-[11px] text-ink-3 mt-1 block">a que a casa mostrou</span>
        </label>
      </div>
      <label className="block">
        <span className="text-xs font-semibold text-ink-2">Casa de aposta (opcional)</span>
        <input value={casa} onChange={e => setCasa(e.target.value)} maxLength={60} placeholder="Betano, Bet365..."
          className={cn(campo, 'mt-1 font-sans')} />
      </label>
      {antigas > 0 && (
        <p className="text-[11px] text-amber-400">
          {antigas} {antigas === 1 ? 'seleção antiga fica' : 'seleções antigas ficam'} de fora: adicione de novo pelo Raio-X pra registrar.
        </p>
      )}
      {erro && <p className="text-sm text-red-400">{erro}</p>}
      <button onClick={registrar} disabled={!valido || enviando}
        className="w-full h-12 rounded-lg bg-accent text-on-fill font-bold disabled:opacity-40">
        {enviando ? 'Registrando…' : `Registrar ${validas.length} ${validas.length === 1 ? 'seleção' : 'seleções'}`}
      </button>
    </div>
  )
}
