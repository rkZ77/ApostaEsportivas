import { useEffect, useState } from 'react'
import { ChevronRight, Sparkles } from 'lucide-react'
import api from '../../services/api'
import { cn } from '../../lib/cn'
import { Skeleton } from '../ui'
import { TeamLogo } from '../TeamLogo'

/*
 * Aba "Leitura IA" do Raio-X (12/10/2026, pedido do usuário).
 *
 * O servidor gera na primeira abertura da aba no dia e guarda (resumo_ia.py):
 * quem abre depois recebe pronto. Na primeira vez ele espera o modelo, por
 * isso o prazo maior.
 *
 * POR TIME, RESPEITANDO O MANDO (mesmo dia, pedido do usuário): um bloco do
 * mandante lido nos jogos em CASA e um do visitante lido nos jogos FORA, cada
 * um com o perfil (dominante, ofensivo...) e os mercados do próprio time.
 * Depois, as linhas do jogo em que os dois concordam.
 *
 * Todo caso sem leitura diz o porquê: um bloco que sumia parecia defeito.
 */

type Tendencia = 'over' | 'under' | 'dividido'
/** A linha do mercado em campos, pra abrir a aba Mercados nela (19/10/2026). */
export interface AtalhoDaIA {
  mercado: string; de_quem: 'jogo' | 'mandante' | 'visitante'
  periodo: 'total' | '1t' | '2t'; lado: 'mais' | 'menos'; linha: number
}
export interface Mercado { mercado: string; tendencia: Tendencia; leitura: string; pct?: number; atalho?: AtalhoDaIA }
/** Números do time no mando desta partida, calculados no servidor (nunca pela IA). */
interface NumerosDoTime {
  jogos?: number; forma?: string; gols_pro?: number; gols_contra?: number
  pct_marcou?: number; pct_sofreu?: number; escanteios_pro?: number
}
type Perfil = 'dominante' | 'ofensivo' | 'equilibrado' | 'defensivo' | 'reativo'
interface LeituraDoTime {
  lado: 'mandante' | 'visitante'; perfil: Perfil; leitura: string; mercados: Mercado[]
  /** Mercados de jogador no mando da partida (19/10/2026). Ausente em leitura antiga. */
  jogadores?: Mercado[]
}
interface Resumo {
  status: 'ok' | 'inelegivel' | 'bloqueado' | 'limite' | 'falhou' | 'desligado'
  motivo?: string; resumo?: string; times?: LeituraDoTime[]; mercados_do_jogo?: Mercado[]
  contexto?: string; alerta?: string
  numeros?: { mandante?: NumerosDoTime; visitante?: NumerosDoTime }
  /** A leitura já leu os titulares confirmados (19/10/2026). */
  escalacao_oficial?: boolean
}
interface Props {
  fixtureId: number
  homeId?: number; awayId?: number; homeNome?: string; awayNome?: string
  /** Tocar num mercado com atalho abre a aba Mercados naquela linha. */
  onAbrirMercado?: (a: AtalhoDaIA) => void
  /** Tocar num mercado de jogador abre a aba Jogadores. */
  onAbrirJogadores?: () => void
}

const TOM: Record<Tendencia, string> = {
  over: 'bg-accent/10 text-accent-ink border-accent/25',
  under: 'bg-sky-500/10 text-sky-300 border-sky-500/25',
  dividido: 'bg-surface-3 text-ink-3 border-line-strong',
}
const ROTULO: Record<Tendencia, string> = { over: 'Over', under: 'Under', dividido: 'Dividido' }
const PERFIL: Record<Perfil, string> = {
  dominante: 'Dominante', ofensivo: 'Ofensivo', equilibrado: 'Equilibrado',
  defensivo: 'Defensivo', reativo: 'Reativo',
}

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

export default function ResumoDaIA({ fixtureId, homeId, awayId, homeNome, awayNome, onAbrirMercado, onAbrirJogadores }: Props) {
  /* Só liga o toque quando o atalho aponta um quadro de linha que existe:
     leitura antiga não tem atalho, e "outro" (resultado, ambas) não tem linha. */
  const abrir = onAbrirMercado && ((m: Mercado) =>
    m.atalho && m.atalho.mercado !== 'outro' ? () => onAbrirMercado(m.atalho!) : undefined)
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
        <Skeleton className="h-24 w-full mb-2" />
        <Skeleton className="h-24 w-full" />
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

  const time = (lado: 'mandante' | 'visitante') => r.times?.find(t => t.lado === lado)

  return (
    <div className="space-y-3">
      <div className="card p-4">
        <Cabecalho />
        <p className="text-sm text-ink-1 leading-relaxed">{r.resumo}</p>
        {r.escalacao_oficial && (
          <p className="mt-2 text-[11px] text-ink-3">Atualizada com a escalação oficial.</p>
        )}
      </div>

      {([
        ['mandante', homeId, homeNome, 'em casa'],
        ['visitante', awayId, awayNome, 'fora'],
      ] as const).map(([lado, id, nome, mando]) => {
        const t = time(lado)
        if (!t) return null
        return (
          <div key={lado} className="card overflow-hidden">
            <div className="px-4 pt-4 pb-3 flex items-center gap-3">
              <TeamLogo id={id} name={nome ?? ''} size={32} />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-bold text-ink-1 truncate">{nome}</div>
                <div className="text-[11px] text-ink-3">Jogando {mando}</div>
              </div>
              <span className="shrink-0 px-2 py-0.5 rounded-full border border-line-strong bg-surface-2 text-[11px] font-bold text-ink-1">
                {PERFIL[t.perfil] ?? t.perfil}
              </span>
            </div>
            {r.numeros?.[lado] && <FaixaDeNumeros n={r.numeros[lado]!} mando={mando} />}
            <p className="px-4 pb-3 text-sm text-ink-2 leading-relaxed">{t.leitura}</p>
            {!!t.mercados.length && <ListaDeMercados mercados={t.mercados} abrir={abrir} />}
            {!!t.jogadores?.length && (
              <>
                <div className="px-4 pt-3 pb-2 border-t border-line/60 text-[11px] font-bold uppercase tracking-wide text-ink-3">Jogadores</div>
                <ListaDeMercados mercados={t.jogadores} abrir={onAbrirJogadores && (() => onAbrirJogadores)} />
              </>
            )}
          </div>
        )
      })}

      {!!r.mercados_do_jogo?.length && (
        <div className="card overflow-hidden">
          <div className="px-4 pt-3 pb-2 text-[11px] font-bold uppercase tracking-wide text-ink-3">Mercados do jogo</div>
          <ListaDeMercados mercados={r.mercados_do_jogo} abrir={abrir} />
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

/** Também usada pela leitura da liga (ligas/LeituraDaLiga). */
export function ListaDeMercados({ mercados, abrir }: {
  mercados: Mercado[]
  /** Devolve a ação do toque no mercado, ou undefined pra linha sem toque. */
  abrir?: (m: Mercado) => (() => void) | undefined
}) {
  return (
    <div className="divide-y divide-line/60 border-t border-line/60">
      {mercados.map(m => {
        const acao = abrir?.(m)
        const Linha = acao ? 'button' : 'div'
        return (
        <Linha key={m.mercado} type={acao ? 'button' : undefined} onClick={acao}
          className={cn('w-full text-left px-4 py-3 flex items-start gap-3', acao && 'hover:bg-surface-2/60 active:bg-surface-2 transition-colors')}>
          <span className={cn('shrink-0 mt-0.5 w-[68px] text-center py-0.5 rounded border text-[10px] font-bold uppercase tracking-wide', TOM[m.tendencia] ?? TOM.dividido)}>
            {ROTULO[m.tendencia] ?? m.tendencia}
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-bold text-ink-1">{m.mercado}</div>
            <div className="text-xs text-ink-3 leading-snug mt-0.5">{m.leitura}</div>
            {m.pct != null && m.pct >= 0 && m.pct <= 100 && (
              <div className="mt-1.5 flex items-center gap-2">
                <div className="h-1 flex-1 max-w-[160px] bg-surface-3 rounded-full overflow-hidden">
                  <div className={cn('h-full rounded-full', m.tendencia === 'under' ? 'bg-sky-400' : 'bg-accent')}
                    style={{ width: `${m.pct}%` }} />
                </div>
                <span className="font-mono text-[11px] font-bold text-ink-2 tabular-nums">{m.pct}%</span>
              </div>
            )}
          </div>
          {acao && <ChevronRight className="shrink-0 mt-0.5 w-4 h-4 text-ink-4" aria-label="Ver no Raio-X" />}
        </Linha>
        )
      })}
    </div>
  )
}

const num = (v?: number) => v == null ? '—' : v.toLocaleString('pt-BR', { maximumFractionDigits: 1 })

/* Quatro números do time no mando da partida, e a forma recente nele. */
function FaixaDeNumeros({ n, mando }: { n: NumerosDoTime; mando: string }) {
  const celulas: [string, string][] = [
    ['Gols feitos', num(n.gols_pro)],
    ['Gols sofridos', num(n.gols_contra)],
    ['Marcou', n.pct_marcou == null ? '—' : `${n.pct_marcou}%`],
    ['Escanteios', num(n.escanteios_pro)],
  ]
  return (
    <div className="px-4 pb-3">
      <div className="grid grid-cols-4 gap-1.5">
        {celulas.map(([rotulo, valor]) => (
          <div key={rotulo} className="rounded-md bg-surface-2/70 px-2 py-1.5 text-center">
            <div className="font-mono text-base font-black text-ink-1 tabular-nums leading-tight">{valor}</div>
            <div className="text-[10px] text-ink-3 leading-tight mt-0.5">{rotulo}</div>
          </div>
        ))}
      </div>
      {(n.jogos || n.forma) && (
        <div className="mt-2 flex items-center gap-2 text-[11px] text-ink-3">
          {n.jogos ? <span>Média em {n.jogos} jogos {mando}</span> : null}
          {n.forma && (
            <span className="ml-auto flex gap-1" aria-label={`Forma ${mando}: ${n.forma}`}>
              {n.forma.slice(0, 5).split('').map((c, i) => (
                <span key={i} className={cn('w-4 h-4 rounded-sm grid place-items-center text-[9px] font-black',
                  c === 'V' ? 'bg-accent/20 text-accent-ink' : c === 'E' ? 'bg-surface-3 text-ink-2' : 'bg-red-500/15 text-red-400')}>
                  {c}
                </span>
              ))}
            </span>
          )}
        </div>
      )}
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
