import { useEffect, useState } from 'react'
import { Sparkles } from 'lucide-react'
import api from '../../services/api'
import { cn } from '../../lib/cn'
import { Skeleton } from '../ui'

/*
 * Aba "Leitura IA" do Raio-X (12/10/2026, pedido do usuário).
 *
 * O servidor gera na primeira abertura da aba no dia e guarda (resumo_ia.py):
 * quem abre depois recebe pronto. Na primeira vez ele espera o modelo, por
 * isso o prazo maior.
 *
 * Era um bloco acima das abas que SUMIA quando o jogo não tinha resumo · a
 * pessoa não sabia se era defeito. Dentro da aba, todo caso diz o porquê.
 */

interface Mercado { mercado: string; tendencia: 'over' | 'under' | 'dividido'; leitura: string }
interface Resumo {
  status: 'ok' | 'inelegivel' | 'bloqueado' | 'limite' | 'falhou' | 'desligado'
  motivo?: string; resumo?: string; mercados?: Mercado[]; contexto?: string; alerta?: string
}

const TOM: Record<Mercado['tendencia'], string> = {
  over: 'bg-accent/10 text-accent-ink border-accent/25',
  under: 'bg-sky-500/10 text-sky-300 border-sky-500/25',
  dividido: 'bg-surface-3 text-ink-3 border-line-strong',
}
const ROTULO: Record<Mercado['tendencia'], string> = { over: 'Over', under: 'Under', dividido: 'Dividido' }

function semLeitura(r: Resumo | null): string {
  switch (r?.status) {
    case 'inelegivel':
      return r.motivo === 'jogo encerrado'
        ? 'A leitura da IA é de antes do jogo, e este já acabou.'
        : 'Ainda não há jogos suficientes dos dois times nesta temporada para uma leitura confiável '
          + '(precisa de 3 do mandante em casa e 3 do visitante fora).'
    case 'bloqueado': return 'A leitura da IA é do plano Pro.'
    case 'limite': return 'A leitura da IA atingiu o limite de hoje. Volte amanhã.'
    case 'desligado': return 'A leitura da IA está desligada no momento.'
    default: return 'Não deu para gerar a leitura agora. Tente de novo em alguns minutos.'
  }
}

export default function ResumoDaIA({ fixtureId }: { fixtureId: number }) {
  const [r, setR] = useState<Resumo | null>(null)
  const [carregando, setCarregando] = useState(true)

  useEffect(() => {
    let vivo = true
    setR(null)
    setCarregando(true)
    api.get(`/fixtures/${fixtureId}/resumo-ia`, { timeout: 45000 })
      .then(res => { if (vivo) setR(res.data) })
      .catch(() => {})
      .finally(() => { if (vivo) setCarregando(false) })
    return () => { vivo = false }
  }, [fixtureId])

  if (carregando) {
    return (
      <div className="card p-4" aria-busy="true">
        <Cabecalho />
        <p className="text-xs text-ink-3 mb-3">A IA está lendo os números do jogo…</p>
        <Skeleton className="h-3 w-full mb-2" />
        <Skeleton className="h-3 w-5/6 mb-4" />
        <Skeleton className="h-8 w-full mb-2" />
        <Skeleton className="h-8 w-full" />
      </div>
    )
  }
  if (r?.status !== 'ok' || !r.resumo) {
    return (
      <div className="card p-8 text-center">
        <Sparkles className="w-5 h-5 text-ink-4 mx-auto mb-2" aria-hidden />
        <p className="text-sm text-ink-2 leading-relaxed">{semLeitura(r)}</p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="card p-4">
        <Cabecalho />
        <p className="text-sm text-ink-1 leading-relaxed">{r.resumo}</p>
      </div>

      {!!r.mercados?.length && (
        <div className="card divide-y divide-line/60">
          {r.mercados.map(m => (
            <div key={m.mercado} className="px-4 py-3 flex items-start gap-3">
              <span className={cn('shrink-0 mt-0.5 w-[68px] text-center py-0.5 rounded border text-[10px] font-bold uppercase tracking-wide', TOM[m.tendencia] ?? TOM.dividido)}>
                {ROTULO[m.tendencia] ?? m.tendencia}
              </span>
              <div className="min-w-0">
                <div className="text-sm font-bold text-ink-1">{m.mercado}</div>
                <div className="text-xs text-ink-3 leading-snug mt-0.5">{m.leitura}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {(r.contexto || r.alerta) && (
        <div className="card p-4 space-y-2">
          {r.contexto && (
            <>
              <div className="text-[11px] font-bold uppercase tracking-wide text-ink-3">Contexto</div>
              <p className="text-sm text-ink-2 leading-relaxed">{r.contexto}</p>
            </>
          )}
          {r.alerta && (
            <p className="text-xs text-yellow-300/90 leading-relaxed border-l-2 border-yellow-500/40 pl-2.5">
              {r.alerta}
            </p>
          )}
        </div>
      )}

      <p className="text-[10px] text-ink-4 leading-relaxed px-1">
        Leitura automática dos números deste Raio-X. Não é pick nem garantia.
      </p>
    </div>
  )
}

function Cabecalho() {
  return (
    <div className="flex items-center gap-1.5 mb-2">
      <Sparkles className="w-3.5 h-3.5 text-accent-ink" aria-hidden />
      <span className="text-[11px] font-bold uppercase tracking-wide text-ink-2">Leitura da IA</span>
    </div>
  )
}
