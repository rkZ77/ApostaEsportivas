import { useEffect, useState } from 'react'
import { Mail, TrendingDown } from 'lucide-react'
import api from '../services/api'

/*
 * Onde a base para de andar, entre o cadastro e o pagamento.
 *
 * Os cartões de plano logo acima contam ESTOQUE (quantos são VIP hoje). Este
 * painel conta PASSAGEM: de cem pessoas que criaram conta na janela, quantas
 * provaram o contato, quantas chegaram a usar o teste e quantas assinaram.
 * Sem essa quebra, "o teste converte pouco" e "pouca gente chega no teste"
 * viram a mesma frase, e o remédio de um não serve pro outro.
 *
 * A SEGUNDA ETAPA É A QUE NINGUÉM VIA. Desde a saída do CPF o teste VIP nasce
 * da prova de contato, não do cadastro: quem não confirma e-mail nem telefone
 * fica free sem nunca ter visto o produto que a home anuncia. A linha
 * "parados sem verificar" é esse grupo, e é o único número desta tela que
 * corresponde a uma ação (reenviar o convite).
 */

interface Etapa {
  chave: string
  rotulo: string
  usuarios: number
  pct_do_topo: number
  pct_da_anterior: number
}

interface Dados {
  dias: number
  cadastros: number
  etapas: Etapa[]
  parados_sem_verificar: number
  google: { cadastros: number; verificados: number; pct: number }
  senha:  { cadastros: number; verificados: number; pct: number }
  dias_ate_pagar: number | null
}

const JANELAS = [7, 30, 90]

export default function AdminFunil() {
  const [d, setD] = useState<Dados | null>(null)
  const [dias, setDias] = useState(30)
  const [carregando, setCarregando] = useState(true)

  useEffect(() => {
    setCarregando(true)
    api.get('/admin/funil', { params: { days: dias } })
      .then(r => setD(r.data))
      .catch(() => setD(null))
      .finally(() => setCarregando(false))
  }, [dias])

  /* Base vazia não vira painel: quatro zeros em fila não dizem nada e ainda
     ocupam a altura de uma tela no celular. */
  if (!carregando && (!d || d.cadastros === 0)) return null

  return (
    <div className="card p-5 mb-4">
      <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
        <div className="flex items-center gap-2">
          <TrendingDown className="w-4 h-4 text-ink-3" aria-hidden="true" />
          <h3 className="text-sm font-bold text-ink-1">Do cadastro ao pagamento</h3>
        </div>
        <div className="flex gap-1">
          {JANELAS.map(j => (
            <button
              key={j}
              onClick={() => setDias(j)}
              className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition-colors border ${
                dias === j
                  ? 'bg-green-500 border-green-500 text-black'
                  : 'border-line-strong text-ink-2 hover:border-ink-4'
              }`}
            >
              {j}d
            </button>
          ))}
        </div>
      </div>

      {carregando || !d ? (
        <div className="h-40 rounded-lg bg-surface-2/40 animate-pulse" />
      ) : (
        <>
          <ul className="space-y-2 mb-4">
            {d.etapas.map((e, i) => (
              <li key={e.chave}>
                <div className="flex items-baseline justify-between gap-3 mb-1">
                  <span className="text-xs text-ink-2">{e.rotulo}</span>
                  <span className="font-mono text-sm font-bold text-ink-1 tabular-nums">
                    {e.usuarios}
                    <span className="text-ink-4 font-normal text-xs"> ({e.pct_do_topo}%)</span>
                  </span>
                </div>
                {/* A barra é proporcional ao TOPO do funil, e não à etapa
                    anterior: assim o degrau que encolhe aparece como degrau,
                    que é a única coisa que este painel precisa mostrar. */}
                <div className="h-2 rounded-full bg-surface-2 overflow-hidden">
                  <div
                    className={`h-full rounded-full ${
                      i === 0 ? 'bg-ink-4' : i === 1 ? 'bg-blue-500' : i === 2 ? 'bg-yellow-400' : 'bg-green-500'
                    }`}
                    style={{ width: `${Math.max(e.pct_do_topo, 1)}%` }}
                  />
                </div>
                {i > 0 && (
                  <p className="text-[10px] text-ink-4 mt-1">
                    {e.pct_da_anterior}% de quem chegou na etapa anterior
                  </p>
                )}
              </li>
            ))}
          </ul>

          {d.parados_sem_verificar > 0 && (
            <div className="flex items-start gap-2.5 rounded-lg border border-blue-400/25 bg-blue-400/5 px-3.5 py-3 mb-3">
              <Mail className="w-4 h-4 text-blue-400 shrink-0 mt-0.5" aria-hidden="true" />
              <p className="text-xs text-ink-2 leading-relaxed">
                <strong className="text-ink-1">{d.parados_sem_verificar}</strong> contas pararam antes de
                provar o contato. Elas não chegaram a ver o produto: o teste VIP nasce da verificação,
                não do cadastro.
              </p>
            </div>
          )}

          {/* A comparação Google x e-mail e senha mede o TETO da segunda etapa:
              o cadastro pelo Google chega verificado de fábrica. */}
          <div className="grid grid-cols-2 gap-3 mb-3">
            {[
              { rotulo: 'Cadastro por e-mail', v: d.senha },
              { rotulo: 'Cadastro por Google', v: d.google },
            ].map(({ rotulo, v }) => (
              <div key={rotulo} className="rounded-lg border border-line bg-surface-2/40 px-3.5 py-3">
                <p className="text-[11px] text-ink-3 mb-1">{rotulo}</p>
                <p className="font-mono text-lg font-bold text-ink-1 tabular-nums">
                  {v.cadastros === 0 ? '—' : `${v.pct}%`}
                </p>
                <p className="text-[10px] text-ink-4">
                  {v.cadastros === 0
                    ? 'sem cadastro na janela'
                    : `${v.verificados} de ${v.cadastros} verificaram`}
                </p>
              </div>
            ))}
          </div>

          {d.dias_ate_pagar !== null && (
            <p className="text-[11px] text-ink-4">
              Do cadastro ao primeiro pagamento: {d.dias_ate_pagar} dias na mediana.
            </p>
          )}
        </>
      )}
    </div>
  )
}
