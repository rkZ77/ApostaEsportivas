import { useEffect, useState } from 'react'
import { ChevronDown, Sparkles } from 'lucide-react'
import api from '../../services/api'
import { cn } from '../../lib/cn'
import { Skeleton } from '../ui'

/*
 * Leitura da IA no topo do Raio-X (12/10/2026, pedido do usuário).
 *
 * O servidor gera na primeira abertura do jogo no dia e guarda (resumo_ia.py):
 * quem abre depois recebe pronto. Por isso o pedido é separado do Raio-X e tem
 * prazo maior · na primeira vez ele espera o modelo, e a tela não espera junto.
 *
 * Qualquer resposta que não seja "ok" (sem amostra, plano gratuito, limite do
 * dia, falha) some sem aviso: o bloco é um extra, e um card dizendo "não tem"
 * em todo jogo pequeno seria ruído no celular.
 */

interface Mercado { mercado: string; tendencia: 'over' | 'under' | 'dividido'; leitura: string }
interface Resumo { status: string; resumo?: string; mercados?: Mercado[]; contexto?: string; alerta?: string }

const TOM: Record<Mercado['tendencia'], string> = {
  over: 'bg-accent/10 text-accent-ink border-accent/25',
  under: 'bg-sky-500/10 text-sky-300 border-sky-500/25',
  dividido: 'bg-surface-3 text-ink-3 border-line-strong',
}
const ROTULO: Record<Mercado['tendencia'], string> = { over: 'Over', under: 'Under', dividido: 'Dividido' }

export default function ResumoDaIA({ fixtureId }: { fixtureId: number }) {
  const [r, setR] = useState<Resumo | null>(null)
  const [carregando, setCarregando] = useState(true)
  const [aberto, setAberto] = useState(false)
  /* O esqueleto só entra se a resposta demorar, ou seja, se o servidor estiver
     gerando. Resumo guardado e jogo sem resumo respondem na hora, e um bloco
     aparecendo e sumindo em 200ms empurraria as abas no celular. */
  const [demorou, setDemorou] = useState(false)

  useEffect(() => {
    let vivo = true
    setR(null)
    setCarregando(true)
    setDemorou(false)
    setAberto(false)
    const t = setTimeout(() => { if (vivo) setDemorou(true) }, 600)
    api.get(`/fixtures/${fixtureId}/resumo-ia`, { timeout: 45000 })
      .then(res => { if (vivo) setR(res.data) })
      .catch(() => {})
      .finally(() => { if (vivo) setCarregando(false); clearTimeout(t) })
    return () => { vivo = false; clearTimeout(t) }
  }, [fixtureId])

  if (carregando) {
    if (!demorou) return null
    return (
      <div className="card p-4 mb-3" aria-busy="true">
        <Cabecalho />
        <p className="text-[11px] text-ink-4 mb-2">Lendo os números do jogo…</p>
        <Skeleton className="h-3 w-full mb-1.5" />
        <Skeleton className="h-3 w-4/5" />
      </div>
    )
  }
  if (r?.status !== 'ok' || !r.resumo) return null

  const temMais = !!(r.contexto || r.alerta)
  return (
    <div className="card p-4 mb-3">
      <Cabecalho />
      <p className="text-sm text-ink-1 leading-relaxed">{r.resumo}</p>

      {!!r.mercados?.length && (
        <ul className="mt-3 space-y-2">
          {r.mercados.map(m => (
            <li key={m.mercado} className="flex items-start gap-2">
              <span className={cn('shrink-0 mt-0.5 px-1.5 py-0.5 rounded border text-[10px] font-bold uppercase tracking-wide', TOM[m.tendencia] ?? TOM.dividido)}>
                {ROTULO[m.tendencia] ?? m.tendencia}
              </span>
              <div className="min-w-0 text-xs leading-snug">
                <span className="font-bold text-ink-1">{m.mercado}</span>
                <span className="text-ink-3"> · {m.leitura}</span>
              </div>
            </li>
          ))}
        </ul>
      )}

      {temMais && (
        <>
          {aberto && (
            <div className="mt-3 space-y-2">
              {r.contexto && <p className="text-xs text-ink-2 leading-relaxed">{r.contexto}</p>}
              {r.alerta && (
                <p className="text-[11px] text-yellow-300/90 leading-relaxed border-l-2 border-yellow-500/40 pl-2.5">
                  {r.alerta}
                </p>
              )}
            </div>
          )}
          <button type="button" onClick={() => setAberto(a => !a)} aria-expanded={aberto}
            className="mt-2 -mb-1 h-9 inline-flex items-center gap-1 text-xs font-semibold text-ink-3 hover:text-ink-1 transition-colors">
            {aberto ? 'Menos' : 'Contexto do jogo'}
            <ChevronDown className={cn('w-3.5 h-3.5 transition-transform', aberto && 'rotate-180')} />
          </button>
        </>
      )}

      <p className="mt-2 text-[10px] text-ink-4 leading-relaxed">
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
