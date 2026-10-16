import type { ReactNode } from 'react'
import { AlertTriangle, ArrowRight, CheckCircle2, Database, Gauge, Trophy, Users, Wallet } from '../lib/icones'
import { cn } from '../lib/cn'

/*
 * ABA "HOJE" DO ADMIN (14/10/2026, pedido do usuário: "a aba de admin está
 * bem ruim pra ver as coisas").
 *
 * Triagem, e não resumo: em 06/10 a "Visão geral" saiu porque repetia números
 * que moram em outras abas e ficava um passo atrás delas. Aqui cada bloco é
 * curto e leva pra aba onde se age · o detalhe continua lá. O que esta tela
 * tem de próprio é a ORDEM: primeiro o que está errado agora (alertas), depois
 * o dia, depois ontem, depois clientes e dinheiro.
 */

export interface ContagemHoje { n: number; pendentes: number }
export interface ResultadoOntem { green: number; red: number; push: number; pendentes: number }
export interface OverviewHoje {
  usuarios: Record<string, number>
  picks_hoje: Record<string, ContagemHoje>
  ontem?: Record<string, ResultadoOntem>
  pendentes_antigos?: number
  coleta: { jogos_hoje: number; jogos_por_comecar: number; jogos_com_odds: number } | null
  financeiro: { receita_mes: number; pagamentos_mes: number } | null
  api_football: { usado: number | null; limite: number | null; pct: number | null } | null
  pipeline: { status?: string; finished_at?: string | null; error?: string | null }
}

interface Props {
  overview: OverviewHoje | null
  rotulos: Record<string, string>
  irPara: (aba: string) => void
}

const brl = (v: number) => v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 })

function Bloco({ titulo, Icon, aba, irPara, children }: {
  titulo: string; Icon: typeof Gauge; aba: string; irPara: (a: string) => void; children: ReactNode
}) {
  return (
    <div className="card p-4 flex flex-col gap-3 min-w-0">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-bold text-ink-1">
          <Icon className="w-4 h-4 text-ink-3" aria-hidden /> {titulo}
        </h3>
        <button type="button" onClick={() => irPara(aba)}
          className="inline-flex items-center gap-1 text-[11px] font-semibold text-ink-3 hover:text-ink-1 min-h-[32px] px-1">
          Abrir <ArrowRight className="w-3 h-3" aria-hidden />
        </button>
      </div>
      {children}
    </div>
  )
}

function Numero({ valor, rotulo, tom }: { valor: ReactNode; rotulo: string; tom?: 'ruim' | 'bom' }) {
  return (
    <div className="bg-surface-1 rounded-md px-3 py-2 min-w-0">
      <div className={cn('font-mono text-xl font-black tabular-nums leading-tight',
        tom === 'ruim' ? 'text-red-400' : tom === 'bom' ? 'text-green-400' : 'text-ink-1')}>{valor}</div>
      <div className="text-[11px] text-ink-3 truncate">{rotulo}</div>
    </div>
  )
}

export default function AdminHoje({ overview, rotulos, irPara }: Props) {
  if (!overview) {
    return <div className="card p-8 text-center text-sm text-ink-3">Carregando o retrato do dia…</div>
  }
  const { usuarios: u, picks_hoje: picks, coleta, api_football: api, financeiro, pipeline } = overview
  const ontem = overview.ontem ?? {}

  const alertas: Array<{ texto: string; aba: string }> = []
  if (coleta && coleta.jogos_hoje > 0 && coleta.jogos_com_odds === 0)
    alertas.push({ texto: `Nenhum dos ${coleta.jogos_hoje} jogos de hoje tem odd: os motores não vão gerar pick.`, aba: 'pipeline' })
  if ((api?.pct ?? 0) >= 90)
    alertas.push({ texto: `Cota da API-Football em ${api?.pct}%: a coleta para quando chegar em 100%.`, aba: 'pipeline' })
  if (pipeline?.status === 'error')
    alertas.push({ texto: 'A última rodada do pipeline terminou com etapa falhando.', aba: 'pipeline' })
  if ((overview.pendentes_antigos ?? 0) > 0)
    alertas.push({ texto: `${overview.pendentes_antigos} pick(s) de antes de ontem ainda sem resultado.`, aba: 'picks' })
  if ((u.vip_expirando ?? 0) > 0)
    alertas.push({ texto: `${u.vip_expirando} assinatura(s) vencem nos próximos 7 dias.`, aba: 'usuarios' })

  const totalHoje = Object.values(picks).reduce((s, p) => s + (p?.n ?? 0), 0)
  const pendHoje = Object.values(picks).reduce((s, p) => s + (p?.pendentes ?? 0), 0)
  const somaOntem = Object.values(ontem).reduce(
    (s, r) => ({ green: s.green + r.green, red: s.red + r.red, push: s.push + r.push }),
    { green: 0, red: 0, push: 0 })
  const decididos = somaOntem.green + somaOntem.red

  return (
    <div className="space-y-4">
      {/* 1. O que está errado agora */}
      {alertas.length ? (
        <div className="card border-amber-500/40 p-4 space-y-2">
          <h3 className="flex items-center gap-2 text-sm font-bold text-amber-300">
            <AlertTriangle className="w-4 h-4" aria-hidden /> Precisa de atenção
          </h3>
          <ul className="space-y-1.5">
            {alertas.map((a, i) => (
              <li key={i}>
                <button type="button" onClick={() => irPara(a.aba)}
                  className="w-full text-left flex items-start justify-between gap-3 text-sm text-ink-1 hover:text-amber-200 min-h-[32px]">
                  <span>{a.texto}</span>
                  <ArrowRight className="w-4 h-4 shrink-0 mt-0.5 text-ink-3" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="card p-4 flex items-center gap-2 text-sm text-ink-2">
          <CheckCircle2 className="w-4 h-4 text-green-400" aria-hidden /> Nada pedindo atenção agora.
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {/* 2. O dia */}
        <Bloco titulo="Picks de hoje" Icon={Trophy} aba="picks" irPara={irPara}>
          <div className="grid grid-cols-2 gap-2">
            <Numero valor={totalHoje} rotulo="publicados" />
            <Numero valor={pendHoje} rotulo="esperando resultado" />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(picks).filter(([, p]) => p?.n).map(([k, p]) => (
              <span key={k} className="text-[11px] px-2 py-1 rounded-full border border-line text-ink-2">
                {rotulos[k] ?? k} <b className="text-ink-1">{p.n}</b>
              </span>
            ))}
            {!totalHoje && <span className="text-xs text-ink-3">Nenhum pick publicado ainda.</span>}
          </div>
        </Bloco>

        {/* 3. Ontem */}
        <Bloco titulo="Como foi ontem" Icon={CheckCircle2} aba="picks" irPara={irPara}>
          <div className="grid grid-cols-3 gap-2">
            <Numero valor={somaOntem.green} rotulo="green" tom="bom" />
            <Numero valor={somaOntem.red} rotulo="red" tom={somaOntem.red ? 'ruim' : undefined} />
            <Numero valor={decididos ? `${Math.round((somaOntem.green / decididos) * 100)}%` : '—'} rotulo="acerto" />
          </div>
          <div className="space-y-1">
            {Object.entries(ontem).map(([k, r]) => (
              <div key={k} className="flex items-center justify-between text-xs text-ink-2">
                <span>{rotulos[k] ?? k}</span>
                <span className="tabular-nums">
                  <b className="text-green-400">{r.green}</b> · <b className="text-red-400">{r.red}</b>
                  {r.push ? <> · {r.push} dev.</> : null}
                  {r.pendentes ? <span className="text-amber-300"> · {r.pendentes} sem resultado</span> : null}
                </span>
              </div>
            ))}
            {!Object.keys(ontem).length && <p className="text-xs text-ink-3">Sem pick ontem.</p>}
          </div>
        </Bloco>

        {/* 4. Coleta e cota */}
        <Bloco titulo="Coleta e API" Icon={Database} aba="pipeline" irPara={irPara}>
          <div className="grid grid-cols-3 gap-2">
            <Numero valor={coleta?.jogos_hoje ?? '—'} rotulo="jogos hoje" />
            <Numero valor={coleta?.jogos_com_odds ?? '—'} rotulo="com odd"
              tom={coleta && coleta.jogos_hoje > 0 && !coleta.jogos_com_odds ? 'ruim' : undefined} />
            <Numero valor={coleta?.jogos_por_comecar ?? '—'} rotulo="por começar" />
          </div>
          {api && (
            <div>
              <div className="flex justify-between text-[11px] text-ink-3 mb-1">
                <span>Cota da API hoje</span>
                <span className="tabular-nums">{api.usado ?? '-'} / {api.limite ?? '-'}</span>
              </div>
              <div className="h-1.5 bg-surface-2 rounded-full overflow-hidden">
                <div className={cn('h-full rounded-full',
                  (api.pct ?? 0) >= 90 ? 'bg-red-500' : (api.pct ?? 0) >= 70 ? 'bg-orange-500' : 'bg-green-500')}
                  style={{ width: `${Math.min(100, api.pct ?? 0)}%` }} />
              </div>
            </div>
          )}
        </Bloco>

        {/* 5. Clientes */}
        <Bloco titulo="Usuários" Icon={Users} aba="usuarios" irPara={irPara}>
          <div className="grid grid-cols-3 gap-2">
            <Numero valor={u.ativos_hoje ?? 0} rotulo="entraram hoje" />
            <Numero valor={u.novos_semana ?? 0} rotulo="novos na semana" />
            <Numero valor={u.vip ?? 0} rotulo="assinantes" />
          </div>
          <p className="text-[11px] text-ink-3">
            {u.trial ?? 0} em teste · {u.free ?? 0} no grátis · {u.ativos_semana ?? 0} entraram na semana
          </p>
        </Bloco>

        {/* 6. Dinheiro */}
        <Bloco titulo="Dinheiro do mês" Icon={Wallet} aba="financeiro" irPara={irPara}>
          <div className="grid grid-cols-2 gap-2">
            <Numero valor={brl(Number(financeiro?.receita_mes ?? 0))} rotulo="receita aprovada" />
            <Numero valor={financeiro?.pagamentos_mes ?? 0} rotulo="pagamentos" />
          </div>
        </Bloco>

        <Bloco titulo="Motor" Icon={Gauge} aba="motor" irPara={irPara}>
          <p className="text-xs text-ink-2">
            Última rodada do pipeline:{' '}
            <b className={pipeline?.status === 'error' ? 'text-red-400' : pipeline?.status === 'ok' ? 'text-green-400' : 'text-ink-1'}>
              {pipeline?.status === 'ok' ? 'concluída' : pipeline?.status === 'error' ? 'com falha'
                : pipeline?.status === 'running' ? 'rodando agora' : 'sem registro desde o último deploy'}
            </b>
          </p>
          <p className="text-[11px] text-ink-3">
            Por que um jogo ou liga não teve pick: aba Motor, "Por que não saiu pick?".
          </p>
        </Bloco>
      </div>
    </div>
  )
}
