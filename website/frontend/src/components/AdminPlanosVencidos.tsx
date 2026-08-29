import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, RefreshCw } from 'lucide-react'
import api from '../services/api'

/*
 * Quem venceu e continua marcado como VIP/trial.
 *
 * O rebaixamento é preguiçoso: acontece quando a pessoa aparece (login,
 * refresh, /auth/me). Isso cobre quem volta, e deixa de fora exatamente quem
 * parou de abrir o site · a conta fica listada como "trial" pra sempre e o
 * e-mail de "seu teste acabou" nunca sai, que é o único aviso capaz de
 * alcançar essa pessoa.
 *
 * A varredura automática pega carona numa visita qualquer ao site (mesmo
 * padrão da resolução de resultado), então este painel quase sempre mostra
 * zero. Ele existe pros dois momentos em que a carona não serve: logo depois
 * de mexer em vencimento na mão, e quando se quer o número na hora.
 *
 * Mostra a lista ANTES de agir de propósito: rodar a varredura manda e-mail
 * de verdade, e um clique no escuro não pode ser a forma de descobrir pra
 * quantas pessoas ele foi.
 */

interface Pendente {
  id: number
  name: string
  email: string
  plan: string
  expires_at: string
  last_login_at: string | null
}

interface Dados {
  total: number
  pendentes: Pendente[]
  varredura: { habilitada: boolean }
}

interface Resumo {
  rebaixados: number
  trial: number
  vip: number
}

export default function AdminPlanosVencidos() {
  const [d, setD] = useState<Dados | null>(null)
  const [rodando, setRodando] = useState(false)
  const [resumo, setResumo] = useState<Resumo | null>(null)
  const [erro, setErro] = useState('')

  const carregar = () =>
    api.get('/admin/users/planos-vencidos')
      .then(r => setD(r.data))
      .catch(() => setD(null))

  useEffect(() => { carregar() }, [])

  const varrer = async () => {
    setRodando(true)
    setErro('')
    try {
      const { data } = await api.post('/admin/users/expirar-planos')
      setResumo(data)
      await carregar()
    } catch {
      setErro('Não foi possível rodar a varredura. Tente de novo.')
    } finally {
      setRodando(false)
    }
  }

  if (!d) return null

  const dias = (iso: string) =>
    Math.floor((Date.now() - new Date(iso).getTime()) / 86400000)

  return (
    <div className="bg-surface-1 border border-line rounded-lg p-4 mb-6">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h3 className="text-xs font-semibold text-ink-3 flex items-center gap-1.5">
          {d.total > 0
            ? <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
            : <CheckCircle2 className="w-3.5 h-3.5 text-green-400" />}
          Planos vencidos sem rebaixar
        </h3>
        <button
          onClick={varrer}
          disabled={rodando || d.total === 0 || !d.varredura.habilitada}
          className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-line-strong text-ink-2 hover:text-ink-1 hover:border-ink-4 disabled:opacity-30 transition-colors flex items-center gap-1.5"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${rodando ? 'animate-spin' : ''}`} />
          {rodando ? 'Rodando...' : 'Rodar varredura'}
        </button>
      </div>

      {d.total === 0 ? (
        <p className="text-[11px] text-ink-4 mt-2 leading-relaxed">
          Ninguém pendente · todo VIP e teste vencido já voltou pro plano free e
          recebeu o aviso.
        </p>
      ) : (
        <>
          <div className="mt-3 space-y-1.5">
            {d.pendentes.map(p => (
              <div key={p.id} className="bg-surface-2 rounded-md px-3 py-2 flex items-center justify-between gap-3 flex-wrap">
                <div className="min-w-0">
                  <div className="text-ink-1 text-sm font-semibold truncate">{p.name}</div>
                  <div className="text-[11px] text-ink-4 truncate">{p.email}</div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-[11px] font-semibold text-amber-400 uppercase">{p.plan}</div>
                  <div className="text-[10px] text-ink-4">
                    venceu há {dias(p.expires_at)}d
                    {p.last_login_at ? '' : ' · nunca entrou'}
                  </div>
                </div>
              </div>
            ))}
          </div>
          <p className="text-[11px] text-ink-4 mt-3 leading-relaxed">
            {d.varredura.habilitada
              ? 'A varredura volta essas contas pro free, cria o aviso no sino e manda o e-mail de fim de acesso · um por pessoa.'
              : 'Varredura desligada neste ambiente. O aviso e o e-mail saem juntos, e aqui o e-mail não sai · rodar só queimaria o aviso da pessoa.'}
          </p>
        </>
      )}

      {resumo && (
        <p className="text-[11px] text-green-400 mt-2">
          {resumo.rebaixados} conta(s) rebaixada(s) · {resumo.trial} teste, {resumo.vip} VIP.
        </p>
      )}
      {erro && <p className="text-[11px] text-red-400 mt-2">{erro}</p>}
    </div>
  )
}
