import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Activity, AlertTriangle, CheckCircle2, Gavel, Play, RefreshCw, XCircle,
} from 'lucide-react'
import api from '../services/api'
import { Spinner } from './ui'

/*
 * Painel do Motor Ao Vivo · acompanhar e testar, nada mais.
 *
 * Saiu de dentro da aba Pipeline por um motivo prático: lá ele era um bloco
 * entre outros seis, sem espaço pra mostrar o que a rodada produziu. Testar o
 * motor é um ciclo (dispara · vê o log · vê os picks · liquida · confere a
 * taxa) e esse ciclo não cabia num cartão.
 *
 * O QUE MUDA DE VERDADE AQUI é o polling. O status da rodada era lido UMA vez,
 * na montagem da página: quem clicava em executar via "rodando" e nunca via
 * terminar, porque nada voltava a perguntar. Numa rodada que leva até 3 minutos
 * (o timeout do subprocesso) isso é a diferença entre painel e enfeite.
 *
 * O polling só existe enquanto há rodada em andamento · painel aberto e parado
 * não fica batendo no servidor.
 */

interface Checagem { item: string; ok: boolean; detalhe: string }
interface Diagnostico {
  pronto: boolean; checagens: Checagem[]; dry_run_padrao: string
  /** "produção" | "desenvolvimento" · onde a rodada grava. */
  grava_em?: string
}
interface RunStatus {
  status: 'idle' | 'running' | 'ok' | 'error'
  started_at: string | null
  finished_at: string | null
  returncode: number | null
  log?: string
  error?: string | null
}
interface Stats {
  disponivel: boolean
  total_gerados: number; expirados: number; pendentes: number; resolvidos: number
  greens: number; reds: number; push: number
  win_rate: number; profit: number; roi: number
  ev_medio: number | null; confianca_media: number | null; minuto_medio: number | null
  por_mercado?: { market_type: string; resolvidos: number; greens: number; profit: number }[]
}

const POLL_MS = 3000

/*
 * Janela do histórico. O feed nasceu servindo a aba pública, onde "ao vivo"
 * significa hoje e ontem · aqui a pergunta é outra ("o motor está acertando?")
 * e ela não cabe em dois dias.
 *
 * Sem isto o painel se contradizia na mesma tela: as estatísticas do topo
 * contam o histórico inteiro, então o cabeçalho dizia 5 resolvidos e a lista
 * logo abaixo mostrava 2 · escondendo justamente as 3 que formaram o número.
 */
const PERIODOS = [
  { dias: 1,   label: 'hoje e ontem' },
  { dias: 7,   label: '7 dias' },
  { dias: 30,  label: '30 dias' },
  { dias: 365, label: 'tudo' },
] as const

/** "2026-08-16" -> "16/08". Por fatia de string, nunca `new Date`: match_date é
 *  DATE pura e o construtor a interpreta como UTC, o que volta um dia atrás
 *  no fuso de Brasília. */
const diaMes = (d?: string | null) =>
  d ? d.slice(5, 10).split('-').reverse().join('/') : '·'

export default function AdminMotorLive() {
  const [diag, setDiag]       = useState<Diagnostico | null>(null)
  const [run, setRun]         = useState<RunStatus | null>(null)
  const [stats, setStats]     = useState<Stats | null>(null)
  const [picks, setPicks]     = useState<any[]>([])
  const [dryRun, setDryRun]   = useState(true)
  const [fixture, setFixture] = useState('')
  const [maxPart, setMaxPart] = useState('')
  const [dias, setDias]       = useState<number>(PERIODOS[1].dias)
  const [logAberto, setLogAberto] = useState(false)
  const [erro, setErro]       = useState('')
  const [carregando, setCarregando] = useState(true)
  const [liquidando, setLiquidando] = useState(false)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  const buscarResultado = useCallback(async () => {
    // Feed e stats falham separado do diagnóstico de propósito: antes da
    // primeira rodada a tabela picks_live não existe e os dois respondem
    // `disponivel: false` · isso não é erro do painel.
    const [f, s] = await Promise.allSettled([
      // limit no teto do endpoint: aqui a lista é material de auditoria, não
      // vitrine · truncar em 40 recriaria em silêncio o problema que a janela
      // de período veio resolver.
      api.get('/live-picks/feed', { params: { limit: 100, dias } }),
      api.get('/live-picks/stats'),
    ])
    if (f.status === 'fulfilled') setPicks(f.value.data?.picks ?? [])
    if (s.status === 'fulfilled') setStats(s.value.data?.disponivel ? s.value.data : null)
  }, [dias])

  const buscarTudo = useCallback(async () => {
    try {
      const [d, r] = await Promise.allSettled([
        api.get('/live-picks/diagnostico'),
        api.get('/live-picks/run-status'),
      ])
      if (d.status === 'fulfilled') setDiag(d.value.data)
      if (r.status === 'fulfilled') setRun(r.value.data)
      await buscarResultado()
    } finally {
      setCarregando(false)
    }
  }, [buscarResultado])

  useEffect(() => { buscarTudo() }, [buscarTudo])

  // Enquanto roda, pergunta de novo. Ao terminar, recarrega o que a rodada
  // produziu e para o relógio · nenhum intervalo sobra rodando em painel parado.
  useEffect(() => {
    const rodando = run?.status === 'running'
    if (!rodando) {
      if (timer.current) { clearInterval(timer.current); timer.current = null }
      return
    }
    timer.current = setInterval(async () => {
      try {
        const { data } = await api.get('/live-picks/run-status')
        setRun(data)
        if (data.status !== 'running') await buscarResultado()
      } catch { /* rodada continua; erro de rede não derruba o painel */ }
    }, POLL_MS)
    return () => { if (timer.current) { clearInterval(timer.current); timer.current = null } }
  }, [run?.status, buscarResultado])

  const rodar = async () => {
    setErro('')
    try {
      await api.post('/live-picks/run', {
        dry_run:      dryRun,
        fixture_id:   fixture.trim() ? Number(fixture.trim()) : null,
        max_partidas: maxPart.trim() ? Number(maxPart.trim()) : null,
      })
      setRun(r => ({ ...(r ?? {} as RunStatus), status: 'running', finished_at: null, started_at: null, returncode: null }))
      setLogAberto(true)
    } catch (e: any) {
      setErro(e.response?.data?.detail || 'Falha ao disparar a rodada.')
    }
  }

  const liquidar = async () => {
    setLiquidando(true)
    setErro('')
    try {
      await api.post('/live-picks/settle')
      await buscarResultado()
    } catch (e: any) {
      setErro(e.response?.data?.detail || 'Falha ao liquidar.')
    } finally {
      setLiquidando(false)
    }
  }

  if (carregando) return <div className="flex justify-center py-12"><Spinner /></div>

  const rodando = run?.status === 'running'

  return (
    <div className="space-y-4">
      {/* ── Cabeçalho + estado de prontidão ───────────────────────────────── */}
      <div className="bg-surface-1 border border-line rounded-lg p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-sm font-bold text-ink-1 flex items-center gap-2">
              <Activity className="w-4 h-4 text-red-400" />
              Motor Ao Vivo
            </h2>
            <p className="text-[11px] text-ink-4 mt-1 leading-relaxed">
              Uma rodada por clique, sem agendamento, porque o consumo precisa ser medido rodada a
              rodada antes de qualquer automação. Analisa partidas ao vivo de ligas cadastradas
              e só consulta odd de quem passa na triagem.
            </p>
          </div>
          <button
            onClick={buscarTudo}
            className="shrink-0 text-ink-4 hover:text-ink-1 transition-colors"
            aria-label="Atualizar"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Onde o pick vai parar. É a informação que decide se a rodada é teste
            ou produção, e ela não pode ficar implícita num painel de admin.
            Vem do servidor · o painel não adivinha o ambiente. */}
        {diag?.grava_em === 'produção' ? (
          <div className="mt-3 flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/[0.08] px-3 py-2">
            <AlertTriangle className="w-3.5 h-3.5 text-red-400 shrink-0 mt-0.5" />
            <p className="text-[11px] text-ink-2 leading-relaxed">
              Esta rodada grava no banco de <b className="text-red-300">PRODUÇÃO</b>
              {' '}(<span className="font-mono text-red-300">LIVE_ENGINE_ALLOW_PROD</span> ligado).
              O pick gerado é real e entra na base de verdade. Use dry run enquanto estiver testando.
            </p>
          </div>
        ) : (
          <div className="mt-3 flex items-start gap-2 rounded-md border border-amber-500/25 bg-amber-500/[0.07] px-3 py-2">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-0.5" />
            <p className="text-[11px] text-ink-2 leading-relaxed">
              O disparo roda com <span className="font-mono text-amber-300">DB_ENV=dev</span>, então o
              pick vai pro banco de <b>desenvolvimento</b> mesmo clicando daqui da produção. Pra gravar
              na base real, ligue <span className="font-mono text-amber-300">LIVE_ENGINE_ALLOW_PROD=true</span>.
            </p>
          </div>
        )}
      </div>

      {/* ── Diagnóstico · sempre visível ──────────────────────────────────── */}
      <div className="bg-surface-1 border border-line rounded-lg p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-semibold text-ink-3">Pré-condições</h3>
          {diag && (
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${
              diag.pronto
                ? 'text-green-400 border-green-500/30 bg-green-500/10'
                : 'text-amber-400 border-amber-500/30 bg-amber-500/10'}`}>
              {diag.pronto ? 'pronto pra rodar' : 'falta configurar'}
            </span>
          )}
        </div>
        {/* Lista completa mesmo quando tudo passa: num painel de teste, saber
            QUAL condição está satisfeita vale tanto quanto saber que falta uma. */}
        <ul className="space-y-1.5">
          {diag?.checagens.map(c => (
            <li key={c.item} className="flex items-start gap-2 text-[11px]">
              {c.ok
                ? <CheckCircle2 className="w-3.5 h-3.5 text-green-400 shrink-0 mt-px" />
                : <XCircle className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-px" />}
              <span className={c.ok ? 'text-ink-3' : 'text-ink-1 font-semibold'}>
                {c.item}
                <span className="text-ink-4 font-normal"> · {c.detalhe}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>

      {/* ── Disparo ───────────────────────────────────────────────────────── */}
      <div className="bg-surface-1 border border-line rounded-lg p-4">
        <h3 className="text-xs font-semibold text-ink-3 mb-3">Rodada</h3>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-[11px] text-ink-2 cursor-pointer">
            <input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)}
              className="accent-accent" />
            dry run (calcula e mostra, não grava)
          </label>
          <input
            value={fixture}
            onChange={e => setFixture(e.target.value.replace(/\D/g, ''))}
            placeholder="fixture (opcional)"
            inputMode="numeric"
            className="w-36 bg-surface-2 border border-line rounded-md px-2 py-1 text-[11px] text-ink-1 placeholder:text-ink-4"
          />
          <input
            value={maxPart}
            onChange={e => setMaxPart(e.target.value.replace(/\D/g, ''))}
            placeholder="máx. partidas"
            inputMode="numeric"
            className="w-32 bg-surface-2 border border-line rounded-md px-2 py-1 text-[11px] text-ink-1 placeholder:text-ink-4"
          />
          <button
            onClick={rodar}
            disabled={rodando}
            className="text-[11px] px-3 py-1.5 rounded-md border border-line-strong text-ink-2 hover:border-ink-4 hover:text-ink-1 transition-colors disabled:opacity-30 disabled:cursor-not-allowed flex items-center gap-1.5"
          >
            {rodando
              ? <><Spinner size="sm" className="w-2.5 h-2.5" tone="ink" /> rodando</>
              : <><Play className="w-3 h-3" /> Executar rodada</>}
          </button>
          <button
            onClick={liquidar}
            disabled={liquidando || rodando}
            className="text-[11px] px-3 py-1.5 rounded-md border border-line-strong text-ink-2 hover:border-ink-4 hover:text-ink-1 transition-colors disabled:opacity-30 flex items-center gap-1.5"
          >
            <Gavel className="w-3 h-3" /> {liquidando ? 'liquidando...' : 'Liquidar agora'}
          </button>
          {run && run.status !== 'idle' && (
            <button onClick={() => setLogAberto(!logAberto)}
              className="text-[11px] text-ink-4 hover:text-ink-2 underline">
              {logAberto ? 'esconder log' : 'ver log'}
            </button>
          )}
        </div>

        {(run?.started_at || run?.finished_at) && (
          <p className="text-[11px] text-ink-4 mt-2">
            {run.started_at && <>início {run.started_at}</>}
            {run.finished_at && <> · fim {run.finished_at}</>}
            {run.returncode !== null && (
              <span className={run.returncode === 0 ? ' text-green-400' : ' text-red-400'}>
                {' '}· saída {run.returncode}
              </span>
            )}
          </p>
        )}

        {erro && <p className="text-[11px] text-red-400 mt-2 leading-relaxed">{erro}</p>}

        {logAberto && (run?.log || run?.error) && (
          <pre className={`mt-3 text-[10px] bg-surface-0 rounded p-2 whitespace-pre-wrap break-all overflow-y-auto max-h-96 ${
            run.returncode === 0 ? 'text-ink-2' : 'text-red-400'}`}>
            {run.error || run.log}
          </pre>
        )}
      </div>

      {/* ── O que o motor produziu ────────────────────────────────────────── */}
      {stats && (
        <div className="bg-surface-1 border border-line rounded-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-semibold text-ink-3">Desempenho</h3>
            <span className="text-[10px] text-ink-4">só picks_live, não inclui pré-jogo</span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {[
              { l: 'Gerados',   v: String(stats.total_gerados) },
              { l: 'Pendentes', v: String(stats.pendentes) },
              { l: 'Acerto',    v: `${stats.win_rate}%`, c: stats.win_rate >= 50 ? 'text-green-400' : 'text-ink-1' },
              { l: 'Lucro',     v: `${stats.profit >= 0 ? '+' : ''}${stats.profit.toFixed(2)}u`, c: stats.profit >= 0 ? 'text-green-400' : 'text-red-400' },
            ].map(x => (
              <div key={x.l} className="bg-surface-2 rounded-md px-3 py-2">
                <div className={`font-mono text-lg font-black ${x.c ?? 'text-ink-1'}`}>{x.v}</div>
                <div className="text-[10px] text-ink-4">{x.l}</div>
              </div>
            ))}
          </div>
          <p className="text-[11px] text-ink-4 mt-2 leading-relaxed">
            {stats.greens}G · {stats.reds}R · {stats.push}P em {stats.resolvidos} resolvidos,
            {' '}e {stats.expirados} tiveram a janela da odd fechada antes de alguém pegar
            {stats.minuto_medio !== null && <>, com minuto médio de entrada {stats.minuto_medio}&#39;</>}
          </p>
        </div>
      )}

      {/* ── Picks da rodada ───────────────────────────────────────────────── */}
      <div className="bg-surface-1 border border-line rounded-lg p-4">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <h3 className="text-xs font-semibold text-ink-3">
            Picks gerados {picks.length > 0 && <span className="text-ink-4 font-normal">· {picks.length}</span>}
          </h3>
          <div className="flex items-center gap-0.5">
            {PERIODOS.map(p => (
              <button
                key={p.dias}
                type="button"
                onClick={() => setDias(p.dias)}
                aria-pressed={dias === p.dias}
                className={`px-2 py-1 rounded text-[11px] transition-colors ${
                  dias === p.dias
                    ? 'bg-surface-3 text-ink-1 font-semibold'
                    : 'text-ink-4 hover:text-ink-2 hover:bg-surface-2'}`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
        {picks.length === 0 ? (
          /* Duas causas diferentes pra lista vazia, e dizer a errada custa
             tempo de investigação: sem NENHUM pick resolvido é porque o motor
             nunca gravou; com resolvidos no topo e lista vazia é a janela que
             está curta, e a saída é clicar em "tudo". */
          stats && stats.total_gerados > 0 ? (
            <p className="text-[11px] text-ink-4">
              Nenhum pick neste período, mas existem {stats.total_gerados} no histórico.
              Amplie a janela acima para vê-los.
            </p>
          ) : (
            <p className="text-[11px] text-ink-4">
              Nada ainda. Antes da primeira rodada com <span className="font-mono">--gravar</span> a
              tabela <span className="font-mono">picks_live</span> nem existe, e dry run não grava nada de propósito.
            </p>
          )
        ) : (
          <>
          {/* Mesma razao da aba Pendencias: seis colunas nao cabem no celular,
              e rolagem lateral dentro de pagina que rola pra baixo faz perder a
              linha que se estava lendo. */}
          <ul className="sm:hidden divide-y divide-line/60">
            {picks.map(p => (
              <li key={`m-${p.id}`} className="py-3">
                <div className="flex items-start justify-between gap-2">
                  <span className="text-[12px] text-ink-2 font-semibold leading-snug">
                    {p.home_team_name} x {p.away_team_name}
                  </span>
                  <span className={`text-[10px] font-bold shrink-0 ${
                    p.result === 'GREEN' ? 'text-green-400'
                    : p.result === 'RED' ? 'text-red-400'
                    : p.result ? 'text-ink-3'
                    : 'text-amber-400'}`}>
                    {p.result ?? (p.expiration_reason ? 'expirado' : 'aberto')}
                  </span>
                </div>
                <p className="text-[11px] text-ink-3 mt-0.5">{p.market} {p.line}</p>
                <p className="text-[10px] text-ink-4 font-mono mt-0.5">
                  {diaMes(p.match_date)} · {p.minute_at_creation}&#39; · odd {Number(p.odd).toFixed(2)}
                  {p.ev !== null && p.ev !== undefined && <> · EV {(Number(p.ev) * 100).toFixed(1)}%</>}
                </p>
              </li>
            ))}
          </ul>

          <div className="hidden sm:block overflow-x-auto -mx-4 px-4">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-ink-4 text-left border-b border-line">
                  <th className="pb-2 font-medium">Data</th>
                  <th className="pb-2 font-medium">Jogo</th>
                  <th className="pb-2 font-medium">Mercado</th>
                  <th className="pb-2 font-medium text-right">Min</th>
                  <th className="pb-2 font-medium text-right">Odd</th>
                  <th className="pb-2 font-medium text-right">EV</th>
                  <th className="pb-2 font-medium text-right">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/60">
                {picks.map(p => (
                  <tr key={p.id}>
                    <td className="py-2 pr-2 text-ink-4 font-mono whitespace-nowrap">
                      {diaMes(p.match_date)}
                    </td>
                    <td className="py-2 pr-2 text-ink-2 max-w-[180px] truncate">
                      {p.home_team_name} x {p.away_team_name}
                    </td>
                    <td className="py-2 pr-2 text-ink-3 max-w-[160px] truncate">
                      {p.market} {p.line}
                    </td>
                    <td className="py-2 pr-2 text-right text-ink-4 font-mono">{p.minute_at_creation}&#39;</td>
                    <td className="py-2 pr-2 text-right text-ink-2 font-mono">{Number(p.odd).toFixed(2)}</td>
                    <td className="py-2 pr-2 text-right font-mono text-ink-3">
                      {p.ev !== null && p.ev !== undefined ? `${(Number(p.ev) * 100).toFixed(1)}%` : '·'}
                    </td>
                    <td className="py-2 text-right">
                      <span className={`font-bold ${
                        p.result === 'GREEN' ? 'text-green-400'
                        : p.result === 'RED' ? 'text-red-400'
                        : p.result ? 'text-ink-3'
                        : 'text-amber-400'}`}>
                        {p.result ?? (p.expiration_reason ? 'expirado' : 'aberto')}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </>
        )}
      </div>
    </div>
  )
}
