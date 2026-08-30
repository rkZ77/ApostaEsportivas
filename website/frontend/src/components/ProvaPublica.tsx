import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import api from '../services/api'
import { Skeleton } from './ui'
import { winRate as calcWinRate, fmtUnits, STAKE_LABEL_PADRAO } from '../utils/format'

/*
 * Faixa de números reais, para as telas em que a pessoa está decidindo pagar.
 *
 * POR QUE ELA EXISTE
 * ------------------
 * A Home mostra o histórico, a página de Resultados mostra o histórico, e as
 * duas telas onde a decisão acontece de fato · /planos deslogado e o checkout ·
 * não mostravam um número sequer. A última tela antes de pagar era a única sem
 * prova nenhuma.
 *
 * NENHUM NÚMERO AQUI É ESCRITO À MÃO
 * ----------------------------------
 * Tudo sai de GET /public/results, o mesmo endpoint da Home e da página de
 * Resultados, com `slim=1` porque esta faixa lê três campos e a resposta cheia
 * traz sete blocos. Se a IA parar de publicar, a faixa cai junto · é assim que
 * tem que ser, e é o oposto do contador de prova social fabricada que saiu da
 * home em julho.
 *
 * A legenda do plano de stake vem junto de propósito: sem ela a pessoa compara
 * o lucro em unidades com a banca dela, os números não batem, e o site parece
 * estar mentindo justamente na tela em que ele está pedindo confiança.
 */

interface Resumo {
  total: number
  greens: number
  profit: number
  roi: number
}

export default function ProvaPublica({ compacta = false }: {
  /** Três indicadores em vez de quatro, sem o link · para dentro do checkout. */
  compacta?: boolean
}) {
  const [resumo, setResumo] = useState<Resumo | null>(null)
  const [stakeLabel, setStakeLabel] = useState<string>(STAKE_LABEL_PADRAO)
  const [carregou, setCarregou] = useState(false)

  useEffect(() => {
    let vivo = true
    /* recent_limit=1 e não 0: a rota valida `ge=1` (routers/public.py) e zero
       devolveria 422. Esta faixa não lê `recent`, então é o menor pedido
       possível · com `slim`, a consulta cai de sete blocos para três. */
    api.get('/public/results', { params: { recent_limit: 1, slim: 1 } })
      .then(r => {
        if (!vivo) return
        setResumo(r.data?.summary ?? null)
        if (r.data?.stake_label) setStakeLabel(r.data.stake_label)
      })
      .catch(() => { /* a faixa some · ver abaixo */ })
      .finally(() => { if (vivo) setCarregou(true) })
    return () => { vivo = false }
  }, [])

  /* Sem histórico resolvido não há prova, e uma faixa de zeros ao lado de um
     botão de pagar é pior do que faixa nenhuma. */
  if (carregou && (!resumo || !resumo.total)) return null

  const wr = resumo ? calcWinRate(resumo.greens, resumo.total) : null

  const tiles = [
    { rotulo: 'Win rate', valor: wr != null ? `${wr}%` : null, destaque: true },
    { rotulo: 'Picks resolvidos', valor: resumo ? String(resumo.total) : null, destaque: false },
    { rotulo: 'Lucro', valor: resumo ? fmtUnits(resumo.profit) : null, destaque: true },
    ...(compacta
      ? []
      : [{ rotulo: 'ROI', valor: resumo ? `${Number(resumo.roi ?? 0).toFixed(1)}%` : null, destaque: false }]),
  ]

  return (
    <div className="bg-surface-1 border border-line rounded-lg p-5">
      <div className="flex items-center justify-between gap-3 mb-4">
        <p className="text-ink-2 text-xs font-bold">Histórico público da IA</p>
        {!compacta && (
          <Link
            to="/resultados"
            className="text-[11px] text-accent-ink font-semibold inline-flex items-center gap-1 shrink-0"
          >
            Conferir pick a pick
            <ArrowRight className="w-3 h-3" aria-hidden="true" />
          </Link>
        )}
      </div>

      <div className={`grid gap-3 ${compacta ? 'grid-cols-3' : 'grid-cols-2 sm:grid-cols-4'}`}>
        {tiles.map(t => (
          <div key={t.rotulo} className="bg-surface-0 border border-line rounded-md p-3 text-center">
            {t.valor == null ? (
              <Skeleton className="h-6 w-16 mx-auto" />
            ) : (
              <p className={`font-mono text-lg font-black tabular-nums ${t.destaque ? 'text-accent-ink' : 'text-ink-1'}`}>
                {t.valor}
              </p>
            )}
            <p className="text-[10px] text-ink-4 mt-0.5">{t.rotulo}</p>
          </div>
        ))}
      </div>

      <p className="text-[10px] text-ink-4 mt-3">
        Todo pick publicado entra nessa conta, inclusive os que perderam. Stake: {stakeLabel}.
      </p>
    </div>
  )
}
