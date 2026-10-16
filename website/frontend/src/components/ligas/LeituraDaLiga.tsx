import { useEffect, useState } from 'react'
import { Sparkles } from '../../lib/icones'
import api from '../../services/api'
import { Skeleton } from '../ui'
import { TeamLogo } from '../TeamLogo'
import { ListaDeMercados, type Mercado } from '../jogos/ResumoDaIA'

/*
 * LEITURA DA IA DA LIGA (15/10/2026, pedido do usuário).
 *
 * Gerada 1x por liga por dia no servidor (liga_ia.py) e guardada: quem abre
 * depois recebe pronto. É a MESMA geração que vira o perfil de liga do motor,
 * então abrir aqui não gasta nada a mais do que o motor já gastaria.
 *
 * Todo caso sem leitura diz o porquê, como na Leitura IA do Raio-X.
 */

interface TimeDaLeitura { time: string; leitura: string; team_id: number }
interface Leitura {
  status: 'ok' | 'inelegivel' | 'limite' | 'falhou' | 'desligado'
  motivo?: string
  resumo?: string; tendencias?: Mercado[]
  mando?: string; momento?: string; alerta?: string
  times_over?: TimeDaLeitura[]; times_under?: TimeDaLeitura[]
}

function semLeitura(r: Leitura | null): string {
  switch (r?.status) {
    case 'inelegivel': return 'A temporada ainda tem poucos jogos pra uma leitura confiável da liga.'
    case 'limite': return 'A leitura da IA atingiu o limite de hoje. Volte amanhã.'
    case 'desligado': return 'A leitura da IA está desligada no momento.'
    default: return 'Não deu pra gerar a leitura agora. Tente de novo em alguns minutos.'
  }
}

export default function LeituraDaLiga({ leagueId }: { leagueId: number }) {
  const [r, setR] = useState<Leitura | null>(null)
  const [carregando, setCarregando] = useState(true)

  useEffect(() => {
    let vivo = true
    setR(null)
    setCarregando(true)
    // Prazo maior: na primeira abertura do dia ele espera o modelo.
    api.get('/suggestions/liga/resumo-ia', { params: { league_id: leagueId }, timeout: 45000 })
      .then(res => { if (vivo) setR(res.data) })
      .catch(() => {})
      .finally(() => { if (vivo) setCarregando(false) })
    return () => { vivo = false }
  }, [leagueId])

  if (carregando) {
    return (
      <section className="card p-4" aria-busy="true">
        <Cabecalho />
        <p className="text-xs text-ink-3 mb-3">A IA está lendo os números da liga…</p>
        <Skeleton className="h-3 w-full mb-2" />
        <Skeleton className="h-3 w-4/5 mb-4" />
        <Skeleton className="h-16 w-full" />
      </section>
    )
  }
  if (r?.status !== 'ok' || !r.resumo) {
    return (
      <section className="card p-4">
        <Cabecalho />
        <p className="text-sm text-ink-3 leading-relaxed">{semLeitura(r)}</p>
      </section>
    )
  }

  return (
    <section className="card overflow-hidden">
      <div className="p-4">
        <Cabecalho />
        <p className="text-[15px] text-ink-1 leading-relaxed">{r.resumo}</p>
        {(r.mando || r.momento) && (
          <div className="mt-3 space-y-1.5">
            {r.mando && <Nota rotulo="Mando">{r.mando}</Nota>}
            {r.momento && <Nota rotulo="Agora">{r.momento}</Nota>}
          </div>
        )}
      </div>

      {!!r.tendencias?.length && <ListaDeMercados mercados={r.tendencias} />}

      {(!!r.times_over?.length || !!r.times_under?.length) && (
        <div className="grid sm:grid-cols-2 border-t border-line/60 divide-y sm:divide-y-0 sm:divide-x divide-line/60">
          <Times titulo="Jogos que passam da média" times={r.times_over} />
          <Times titulo="Jogos que ficam abaixo" times={r.times_under} />
        </div>
      )}

      {r.alerta && (
        <p className="mx-4 mb-4 mt-1 text-xs text-yellow-300/90 leading-relaxed border-l-2 border-yellow-500/40 pl-2.5">
          {r.alerta}
        </p>
      )}
      <p className="px-4 pb-3 text-[11px] text-ink-4">
        Leitura automática dos números da temporada, atualizada 1x por dia. Não é pick nem garantia.
      </p>
    </section>
  )
}

function Nota({ rotulo, children }: { rotulo: string; children: React.ReactNode }) {
  return (
    <p className="text-sm text-ink-2 leading-relaxed">
      <span className="text-[11px] font-bold uppercase tracking-wide text-ink-3 mr-1.5">{rotulo}</span>
      {children}
    </p>
  )
}

function Times({ titulo, times }: { titulo: string; times?: TimeDaLeitura[] }) {
  if (!times?.length) return null
  return (
    <div className="px-4 py-3">
      <div className="text-[11px] font-bold uppercase tracking-wide text-ink-3 mb-2">{titulo}</div>
      <ul className="space-y-2.5">
        {times.map(t => (
          <li key={t.team_id} className="flex items-start gap-2.5">
            <TeamLogo id={t.team_id} name={t.time} size={20} />
            <div className="min-w-0">
              <div className="text-sm font-bold text-ink-1 leading-tight">{t.time}</div>
              <div className="text-xs text-ink-3 leading-snug mt-0.5">{t.leitura}</div>
            </div>
          </li>
        ))}
      </ul>
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
