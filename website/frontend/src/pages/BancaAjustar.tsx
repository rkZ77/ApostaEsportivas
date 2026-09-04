import { useEffect, useState, useCallback } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Spinner } from '../components/ui'
import PageShell from '../components/PageShell'
import api from '../services/api'
import { fmtBRL } from '../utils/format'
import NumberTicker from '../components/ui/NumberTicker'

/*
 * Ajustar a banca no meio do mês, sem reconfigurar do zero.
 *
 * O QUE FALTAVA
 * -------------
 * "Configurar" sobrescreve a banca inicial e não deixa rastro do porquê, e por
 * isso é travado em uma vez por mês. O efeito colateral era que a operação
 * legítima mais comum ("subi minha banca de R$500 pra R$1.000 no dia 12") não
 * tinha porta nenhuma: a única existente estava fechada com a chave certa pelo
 * motivo errado.
 *
 * Aqui as duas mudanças que a pessoa realmente quer fazer no meio do mês têm
 * porta própria, e as duas ficam registradas: depósito entra no histórico com
 * data e valor, e a unidade nova vale só daqui pra frente porque cada aposta
 * guarda a unidade que valia quando foi feita.
 *
 * DUAS COISAS NUMA TELA SÓ, e não duas telas: as duas respondem a mesma
 * pergunta ("minha banca mudou, e agora?") e quem entra por uma costuma querer
 * conferir a outra. Separar obrigaria a voltar e escolher de novo.
 */
export default function BancaAjustar() {
  const [current, setCurrent]   = useState(0)
  const [unidade, setUnidade]   = useState(0)
  const [depositos, setDeps]    = useState<any[]>([])
  const [loading, setLoading]   = useState(true)

  const [valor, setValor]       = useState('')
  const [errDep, setErrDep]     = useState('')
  const [savDep, setSavDep]     = useState(false)

  const [novaUnid, setNovaUnid] = useState('')
  const [errUni, setErrUni]     = useState('')
  const [okUni, setOkUni]       = useState('')
  const [savUni, setSavUni]     = useState(false)

  const load = useCallback(() => {
    Promise.all([
      api.get('/banca/summary'),
      api.get('/banca/deposits', { params: { limit: 100 } }),
    ])
      .then(([s, d]) => {
        setCurrent(s.data.bankroll_current ?? 0)
        setUnidade(Number(s.data.unit_value ?? 0))
        setDeps(d.data ?? [])
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const valorNum   = parseFloat(valor.replace(',', '.')) || 0
  const bancaDepois = current + valorNum

  const unidNum   = parseFloat(novaUnid.replace(',', '.')) || 0
  /* O mesmo piso que o servidor cobra, calculado aqui só pra a pessoa ver o
     limite antes de tentar. Quem decide continua sendo o servidor. */
  const unidadesComNova = unidNum > 0 ? current / unidNum : 0
  const unidadeMax      = current > 0 ? Math.floor((current / 20) * 100) / 100 : 0
  const unidadeAlta     = unidNum > 0 && unidadesComNova < 20

  const depositar = async () => {
    setErrDep('')
    if (!valorNum || valorNum <= 0) { setErrDep('Informe um valor maior que zero.'); return }
    setSavDep(true)
    try {
      await api.post('/banca/deposit', { amount: valorNum })
      setValor('')
      load()
    } catch (e: any) {
      setErrDep(e.response?.data?.detail ?? 'Erro ao salvar.')
    } finally {
      setSavDep(false)
    }
  }

  const trocarUnidade = async () => {
    setErrUni(''); setOkUni('')
    if (!unidNum || unidNum <= 0) { setErrUni('Informe um valor maior que zero.'); return }
    setSavUni(true)
    try {
      const { data } = await api.post('/banca/unidade', { unit_value: unidNum })
      setUnidade(Number(data.unit_value))
      setNovaUnid('')
      setOkUni('Pronto. A unidade nova vale das próximas apostas em diante.')
      load()
    } catch (e: any) {
      setErrUni(e.response?.data?.detail ?? 'Erro ao salvar.')
    } finally {
      setSavUni(false)
    }
  }

  return (
    <PageShell
      title="Ajustar banca"
      description="Deposite na banca ou mude o valor da unidade, sem esperar o fechamento do mês."
      noindex
      width="narrow"
      bar={{
        back: '/banca',
        title: 'Ajustar banca',
        sub: 'Sem esperar o fechamento do mês, e sem mexer no que já passou',
      }}
    >
      {loading ? (
        <div className="card p-16 flex items-center justify-center">
          <Spinner size="lg" />
        </div>
      ) : (
        <div className="space-y-6">
          <div className="card p-5 grid grid-cols-2 gap-4">
            <div>
              <p className="text-xs text-ink-3 font-semibold mb-1">Banca atual</p>
              <NumberTicker value={current} formatter={fmtBRL}
                            className="font-mono text-2xl font-black text-ink-1" />
            </div>
            <div>
              <p className="text-xs text-ink-3 font-semibold mb-1">1 unidade vale</p>
              <NumberTicker value={unidade} formatter={fmtBRL}
                            className="font-mono text-2xl font-black text-ink-1" />
            </div>
          </div>

          {/* ── Depósito ───────────────────────────────────────────────── */}
          <div className="card p-5">
            <p className="text-sm font-bold text-ink-1 mb-1">Depositar na banca</p>
            <p className="text-[11px] text-ink-3 leading-relaxed mb-4">
              Entrou dinheiro novo. O valor soma na banca e fica no histórico com
              data, então o seu retorno continua sendo medido contra o que você
              de fato arriscou.
            </p>

            <label className="text-xs text-ink-3 block mb-1.5">Quanto você está depositando? (R$)</label>
            <input
              type="number" min="0.01" step="0.01" value={valor}
              onChange={e => setValor(e.target.value)}
              className="input w-full" placeholder="Ex: 500"
            />

            <AnimatePresence>
              {valorNum > 0 && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.2 }}
                  className="overflow-hidden"
                >
                  <div className="mt-3 bg-surface-2/50 rounded-lg px-3 py-2.5 text-xs flex items-center justify-between">
                    <span className="text-ink-2">Banca depois do depósito</span>
                    <NumberTicker value={bancaDepois} formatter={fmtBRL}
                                  className="font-black text-ink-1" />
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {errDep && <p className="text-red-400 text-xs mt-3">{errDep}</p>}

            <button
              onClick={depositar}
              disabled={savDep || !valorNum}
              className="btn-primary w-full py-2.5 text-sm mt-4 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {savDep ? 'Salvando...' : 'Confirmar depósito'}
            </button>
          </div>

          {/* ── Unidade ────────────────────────────────────────────────── */}
          <div className="card p-5">
            <p className="text-sm font-bold text-ink-1 mb-1">Valor da unidade</p>
            <p className="text-[11px] text-ink-3 leading-relaxed mb-4">
              Vale das próximas apostas em diante. As que já estão registradas
              continuam valendo o que valiam quando você as fez, então mudar aqui
              não mexe em nenhum número que você já viu.
            </p>

            <label className="text-xs text-ink-3 block mb-1.5">Quanto vale 1 unidade? (R$)</label>
            <input
              type="number" min="0.01" step="0.01" value={novaUnid}
              onChange={e => setNovaUnid(e.target.value)}
              className="input w-full" placeholder={unidade ? String(unidade) : 'Ex: 20'}
            />

            <AnimatePresence>
              {unidNum > 0 && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.2 }}
                  className="overflow-hidden"
                >
                  <div className="mt-3 bg-surface-2/50 rounded-lg px-3 py-2.5 text-xs flex items-center justify-between">
                    <span className="text-ink-2">Sua banca em unidades</span>
                    <span className={`font-mono font-black ${unidadeAlta ? 'text-red-400' : 'text-ink-1'}`}>
                      {unidadesComNova.toFixed(0)}u
                    </span>
                  </div>
                  {unidadeAlta && (
                    <p className="text-red-400 text-[11px] mt-2 leading-relaxed">
                      Com menos de 20 unidades uma sequência ruim normal já quebra
                      a banca. O máximo pra {fmtBRL(current)} é {fmtBRL(unidadeMax)}.
                    </p>
                  )}
                </motion.div>
              )}
            </AnimatePresence>

            {errUni && <p className="text-red-400 text-xs mt-3">{errUni}</p>}
            {okUni  && <p className="text-accent-ink text-xs mt-3">{okUni}</p>}

            <button
              onClick={trocarUnidade}
              disabled={savUni || !unidNum || unidadeAlta}
              className="btn-primary w-full py-2.5 text-sm mt-4 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {savUni ? 'Salvando...' : 'Salvar valor da unidade'}
            </button>
          </div>

          <div className="card overflow-hidden">
            <div className="px-5 py-3 border-b border-line">
              <span className="text-xs font-bold text-ink-3">Histórico de depósitos</span>
            </div>
            {depositos.length === 0 ? (
              <p className="text-ink-4 text-sm px-5 py-8 text-center">Nenhum depósito ainda</p>
            ) : (
              <div className="divide-y divide-line/60">
                {depositos.map(d => (
                  <div key={d.id} className="flex items-center gap-3 px-5 py-3">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-bold text-accent-ink">+ {fmtBRL(d.amount)}</p>
                      <p className="text-[11px] text-ink-3 mt-0.5">
                        {new Date(d.created_at).toLocaleDateString('pt-BR', {
                          day: '2-digit', month: '2-digit', year: 'numeric',
                          hour: '2-digit', minute: '2-digit',
                        })}
                      </p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-[10px] text-ink-4">
                        de {fmtBRL(d.bankroll_before)} pra {fmtBRL(d.bankroll_after)}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </PageShell>
  )
}
