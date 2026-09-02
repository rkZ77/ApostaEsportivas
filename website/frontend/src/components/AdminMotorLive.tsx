import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Activity, AlertTriangle, CheckCircle2, Gavel, Play, RefreshCw, Square, XCircle,
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
 * O polling existe enquanto há o que acompanhar · uma rodada avulsa em curso ou
 * o laço contínuo ligado. Painel aberto com tudo parado não bate no servidor.
 *
 * DOIS MODOS, e a ordem na tela reflete qual é o normal:
 *
 *   contínuo   liga e fica disparando rodada atrás de rodada até alguém
 *              desligar. É o modo de operação de verdade · a primeira passada
 *              sobre uma partida não tem janela de ritmo pra ler (a API só dá
 *              acumulado), quem constrói isso é a segunda e a terceira.
 *   avulsa     uma rodada só, geralmente com --fixture, pra testar.
 *
 * O laço mora no processo do backend, não aqui: fechar esta página não desliga
 * nada. Um restart do serviço, sim · e o painel diz isso em vez de fingir.
 *
 * O PAINEL ENCOLHEU EM 28/08, junto com as variáveis do Live no Railway. Saíram
 * os avisos de "grava em dev", "ligue LIVE_ENGINE_ALLOW_PROD" e o selo de
 * visibilidade: o motor virou produto, roda no banco do serviço que o disparou,
 * e alerta que não pode mais disparar é ruído que ensina a ignorar o painel.
 */

interface Checagem { item: string; ok: boolean; detalhe: string }
interface Diagnostico {
  pronto: boolean; checagens: Checagem[]; dry_run_padrao: string
  /**
   * `LIVE_ENGINE_DRY_RUN` já interpretado pelo backend. Vem daí e não de uma
   * leitura do texto aqui porque "off", "0" e "não" são valores válidos que um
   * `=== 'false'` entenderia ao contrário.
   */
  dry_run_padrao_ativo?: boolean
  /** Constante `true` desde 28/08 · a aba não depende mais de variável. */
  publico?: boolean
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
/** Laço de rodadas sucessivas · liga e desliga no clique, nunca sozinho. */
interface Watch {
  ativo: boolean; iniciado_em: string | null; rodadas: number
  falhas_seguidas: number; ultima_rodada: string | null
  proxima_rodada_em: number | null; motivo_parada: string | null
  intervalo_min: number | null; dry_run: boolean | null
}

const POLL_MS = 3000

/** Quanto da cota diária da API-Football o motor ao vivo consumiu.
 *  `ao_vivo` conta as chamadas feitas pelo live_feed (motor) e pelo router
 *  `live` (site) -- os dois gastam a mesma cota pela mesma partida. */
type QuotaAoVivo = {
  hoje?: { dia: string; ao_vivo: number; total: number; pct_do_total: number } | null
  limite?: number | null
  /** Consumo total de hoje pelo /status da própria API-Football, que é a fonte
   *  oficial e enxerga inclusive o que roda fora daqui. */
  usado_total?: number | null
  pct_da_cota?: number | null
  pct_do_usado?: number | null
  dias?: Array<{ dia: string; ao_vivo: number; total: number; pct_do_total: number }>
}

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
  d ? d.slice(5, 10).split('-').reverse().join('/') : '-'

/** "2026-08-28T15:41:36-03:00" -> "15:41". Fatiado, nunca por `new Date`: o
 *  backend já grava no fuso de Brasília (ver _relogio_do_watch em
 *  routers/live_picks.py), e qualquer parse reintroduziria a conversão que
 *  essa escolha existe justamente pra evitar. */
const horaCurta = (iso?: string | null) => (iso ? iso.slice(11, 16) : '')

export default function AdminMotorLive() {
  const [diag, setDiag]       = useState<Diagnostico | null>(null)
  const [run, setRun]         = useState<RunStatus | null>(null)
  const [watch, setWatch]     = useState<Watch | null>(null)
  const [stats, setStats]     = useState<Stats | null>(null)
  const [picks, setPicks]     = useState<any[]>([])
  const [dryRun, setDryRun]   = useState(true)
  /** O checkbox já foi semeado com `LIVE_ENGINE_DRY_RUN`? Só uma vez. */
  const dryRunSemeado = useRef(false)
  const [intervalo, setIntervalo] = useState('8')
  const [fixture, setFixture] = useState('')
  const [maxPart, setMaxPart] = useState('')
  const [dias, setDias]       = useState<number>(PERIODOS[1].dias)
  const [logAberto, setLogAberto] = useState(false)
  const [erro, setErro]       = useState('')
  const [cota, setCota] = useState<QuotaAoVivo | null>(null)
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
      const [d, r, w] = await Promise.allSettled([
        api.get('/live-picks/diagnostico'),
        api.get('/live-picks/run-status'),
        api.get('/live-picks/watch-status'),
      ])
      if (d.status === 'fulfilled') {
        setDiag(d.value.data)
        // O checkbox nascia `true` cravado, e o valor dele SOBRESCREVE a
        // variável de ambiente lá no motor. O efeito era mudar
        // LIVE_ENGINE_DRY_RUN=false no Railway e continuar sem pick nenhum,
        // sem mensagem de erro. Aqui ele passa a nascer no que a variável diz.
        //
        // Uma vez só: trocar o período recarrega o diagnóstico, e re-semear
        // desfaria a escolha de quem já marcou o checkbox na mão.
        if (!dryRunSemeado.current
            && typeof d.value.data?.dry_run_padrao_ativo === 'boolean') {
          setDryRun(d.value.data.dry_run_padrao_ativo)
          dryRunSemeado.current = true
        }
      }
      if (r.status === 'fulfilled') setRun(r.value.data)
      if (w.status === 'fulfilled') setWatch(w.value.data)
      // Cota entra em allSettled próprio: ela é informação lateral, e uma
      // tabela que ainda não existe (banco antigo) não pode derrubar o painel.
      api.get('/admin/api-quota/ao-vivo')
        .then(res => setCota(res.data))
        .catch(() => setCota(null))
      await buscarResultado()
    } finally {
      setCarregando(false)
    }
  }, [buscarResultado])

  useEffect(() => { buscarTudo() }, [buscarTudo])

  // Pergunta de novo enquanto houver o que acompanhar · uma rodada avulsa em
  // andamento, ou o laço contínuo ligado. Parado, nenhum intervalo sobra
  // batendo no servidor.
  //
  // O laço mantém o relógio ligado mesmo entre rodadas de propósito: é a
  // contagem regressiva pra próxima e o contador de rodadas que provam, pra
  // quem está olhando, que ele continua de pé.
  useEffect(() => {
    const acompanhando = run?.status === 'running' || watch?.ativo
    if (!acompanhando) {
      if (timer.current) { clearInterval(timer.current); timer.current = null }
      return
    }
    timer.current = setInterval(async () => {
      try {
        const [r, w] = await Promise.allSettled([
          api.get('/live-picks/run-status'),
          api.get('/live-picks/watch-status'),
        ])
        const rodavaAntes = run?.status === 'running'
        if (r.status === 'fulfilled') {
          setRun(r.value.data)
          if (rodavaAntes && r.value.data.status !== 'running') await buscarResultado()
        }
        if (w.status === 'fulfilled') setWatch(w.value.data)
      } catch { /* rodada continua; erro de rede não derruba o painel */ }
    }, POLL_MS)
    return () => { if (timer.current) { clearInterval(timer.current); timer.current = null } }
  }, [run?.status, watch?.ativo, buscarResultado])

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

  const alternarWatch = async (ligar: boolean) => {
    setErro('')
    try {
      await api.post('/live-picks/watch', {
        ligar,
        intervalo_min: Number(intervalo) || 8,
        dry_run: dryRun,
        max_partidas: maxPart.trim() ? Number(maxPart.trim()) : null,
      })
      const { data } = await api.get('/live-picks/watch-status')
      setWatch(data)
      if (!ligar) await buscarResultado()
    } catch (e: any) {
      setErro(e.response?.data?.detail || 'Falha ao mudar o acompanhamento contínuo.')
    }
  }

  /* CARREGAMENTO NO PADRÃO DO PIPELINE (02/09).
   *
   * Antes: `if (carregando) return <Spinner />` -- tela em branco com uma
   * bolinha no meio até TUDO chegar (diagnóstico, run, watch, feed, stats,
   * cota). Cinco requisições, e a mais lenta definia quando a tela existia.
   *
   * A aba Pipeline não faz isso: ela nasce com o grid desenhado a partir de um
   * fallback e vai preenchendo conforme as respostas chegam. Quem abre vê a
   * estrutura na hora e entende que está carregando, em vez de olhar pro vazio.
   *
   * Aqui o mesmo: a tela renderiza sempre, e cada bloco resolve a própria
   * ausência de dado (`diag` null vira traço, lista vazia vira estado vazio).
   * `carregando` continua existindo, mas só pra marcar os números que ainda não
   * chegaram -- não pra segurar a página. */
  const rodando = run?.status === 'running'
  const emLaco  = !!watch?.ativo

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

        {/* Onde o pick vai parar · a informação que decide se a rodada é teste
            ou produção, e que não pode ficar implícita num painel de admin.
            Vem do servidor · o painel não adivinha o ambiente.

            O aviso ficou UM só, e não dois: desde 28/08 a rodada sempre grava
            no banco deste serviço, então o segundo ramo descrevia um estado que
            não existe mais. O alerta continua vermelho de propósito · o pick
            gerado aqui é o mesmo que o assinante vê. */}
        <div className="mt-3 flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/[0.08] px-3 py-2">
          <AlertTriangle className="w-3.5 h-3.5 text-red-400 shrink-0 mt-0.5" />
          <p className="text-[11px] text-ink-2 leading-relaxed">
            Esta rodada grava no banco <b className="text-red-300">deste serviço</b>. O pick gerado é
            real e o assinante vê na aba Ao Vivo. Marque <b>dry run</b> enquanto estiver testando.
          </p>
        </div>
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
        {/* Onde o motor GRAVA · o painel dizia "rodada concluída" sem nunca
            dizer em qual banco. Num painel que existe pra testar, essa é a
            primeira pergunta · mesmo hoje, que a resposta é sempre a mesma. */}
        {diag?.grava_em && (
          <p className="text-[11px] text-ink-4 mb-2">
            Grava no banco de{' '}
            <span className={diag.grava_em.startsWith('produ') ? 'text-amber-400 font-bold' : 'text-ink-2 font-bold'}>
              {diag.grava_em.toUpperCase()}
            </span>
            {diag.grava_em.startsWith('produ')
              ? ', o pick que sair daqui aparece pro assinante.'
              : ', nada daqui chega ao assinante.'}
          </p>
        )}
        {/* Lista completa mesmo quando tudo passa: num painel de teste, saber
            QUAL condição está satisfeita vale tanto quanto saber que falta uma. */}
        {/* Sem o diagnóstico ainda, linhas fantasma no lugar da lista: é o que
            diz "está vindo" sem segurar a página inteira, no mesmo espírito do
            grid da aba Pipeline. */}
        {!diag && (
          <ul className="space-y-1.5" aria-hidden>
            {[0, 1, 2, 3].map(i => (
              <li key={i} className="flex items-center gap-2">
                <span className="w-3.5 h-3.5 rounded-full bg-surface-2 shrink-0" />
                <span className="h-2.5 rounded bg-surface-2"
                      style={{ width: `${55 + (i % 3) * 12}%` }} />
              </li>
            ))}
          </ul>
        )}
        <ul className="space-y-1.5">
          {diag?.checagens.map(c => (
            <li key={c.item} className="flex items-start gap-2 text-[11px]">
              {c.ok
                ? <CheckCircle2 className="w-3.5 h-3.5 text-green-400 shrink-0 mt-px" />
                : <XCircle className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-px" />}
              <span className={c.ok ? 'text-ink-3' : 'text-ink-1 font-semibold'}>
                {c.item}
                <span className="text-ink-4 font-normal">, {c.detalhe}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>

      {/* ── Cota da API-Football gasta por ESTE motor ─────────────────────── */}
      {/*
        O painel geral do /admin responde "quanto da cota foi usada hoje". Aqui
        a pergunta é outra e mais específica: quanto DISSO foi o ao vivo. É ela
        que decide se dá pra subir LIVE_MAX_MATCHES ou encurtar o intervalo
        entre rodadas -- sem esse número, mexer nos dois é apostar.

        Conta as chamadas do `live_feed` (motor) e do router `live` (site)
        juntas: os dois gastam a mesma cota pela mesma partida, e separá-los
        aqui faria o consumo parecer menor do que é.
      */}
      <div className="bg-surface-1 border border-line rounded-lg p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-semibold text-ink-3">Cota da API gasta pelo Ao Vivo</h3>
          {cota?.limite && (
            <span className="text-[10px] text-ink-4">
              plano de {cota.limite.toLocaleString('pt-BR')}/dia
            </span>
          )}
        </div>

        {!cota ? (
          <div className="grid grid-cols-3 gap-2" aria-hidden>
            {[0, 1, 2].map(i => (
              <div key={i} className="bg-surface-0 rounded-md px-3 py-2 border border-line">
                <div className="h-5 w-12 rounded bg-surface-2" />
                <div className="h-2 w-16 rounded bg-surface-2 mt-1.5" />
              </div>
            ))}
          </div>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-2">
              {[
                { l: 'chamadas hoje', v: String(cota.hoje?.ao_vivo ?? 0) },
                {
                  l: 'da cota do dia',
                  v: cota.pct_da_cota != null ? `${cota.pct_da_cota}%` : '-',
                },
                {
                  /* Do consumo REAL do dia, não da nossa soma: se um coletor
                     rodou de outra máquina, o ao vivo pesa menos do que a
                     contagem local sozinha faria parecer. */
                  l: 'do gasto de hoje',
                  v: cota.pct_do_usado != null ? `${cota.pct_do_usado}%` : '-',
                },
              ].map(x => (
                <div key={x.l} className="bg-surface-0 rounded-md px-3 py-2 border border-line">
                  <div className="font-mono text-sm font-bold text-ink-1 truncate">{x.v}</div>
                  <div className="text-[10px] text-ink-4 leading-tight">{x.l}</div>
                </div>
              ))}
            </div>

            {/* Os dias anteriores dão a régua: um número sozinho não diz se 300
                chamadas é muito. */}
            {(cota.dias?.length ?? 0) > 1 && (
              <ul className="mt-3 pt-3 border-t border-line space-y-1">
                {cota.dias!.slice(0, 6).map(d => (
                  <li key={d.dia} className="flex items-center gap-2 text-[11px]">
                    <span className="text-ink-4 w-16 shrink-0 font-mono">{diaMes(d.dia)}</span>
                    <span className="flex-1 h-1.5 rounded bg-surface-2 overflow-hidden">
                      <span
                        className="block h-full bg-red-400/70"
                        style={{
                          width: `${cota.limite
                            ? Math.min(100, (100 * d.ao_vivo) / cota.limite)
                            : 0}%`,
                        }}
                      />
                    </span>
                    <span className="font-mono text-ink-2 tabular-nums w-12 text-right">
                      {d.ao_vivo}
                    </span>
                  </li>
                ))}
              </ul>
            )}

            <p className="text-[10px] text-ink-4 leading-relaxed mt-3">
              As chamadas do ao vivo são contadas aqui, uma a uma. O total do dia
              {cota.usado_total != null && <> ({cota.usado_total.toLocaleString('pt-BR')})</>}{' '}
              vem do <span className="text-ink-3">/status</span> da própria API, que não
              consome cota e enxerga também o que roda fora daqui.
            </p>
          </>
        )}
      </div>

      {/* ── Acompanhamento contínuo ───────────────────────────────────────── */}
      {/* Vem ANTES do disparo avulso de propósito: com o motor ao vivo, a
          rodada única é a exceção (serve pra testar um fixture), e o laço é o
          modo normal de operar · a primeira passada sobre uma partida não tem
          janela de ritmo pra ler, quem constrói isso é a segunda e a terceira. */}
      <div className={`rounded-lg border p-4 ${
        emLaco ? 'border-green-500/40 bg-green-500/[0.06]' : 'bg-surface-1 border-line'}`}>
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0">
            <h3 className="text-xs font-semibold text-ink-3 flex items-center gap-1.5">
              {emLaco && <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />}
              Acompanhamento contínuo
            </h3>
            <p className="text-[11px] text-ink-4 mt-1 leading-relaxed max-w-xl">
              Dispara uma rodada atrás da outra no intervalo escolhido e não para sozinho, 
              só quando você desligar. Uma passada só não constrói a janela de ritmo que o
              motor usa, são a segunda e a terceira que fazem o modelo valer.
            </p>
          </div>
          <button
            onClick={() => alternarWatch(!emLaco)}
            disabled={rodando && !emLaco}
            className={`shrink-0 text-[11px] font-semibold px-4 py-2 rounded-md border transition-colors disabled:opacity-30 disabled:cursor-not-allowed flex items-center gap-1.5 ${
              emLaco
                ? 'border-red-500/40 text-red-300 hover:bg-red-500/10'
                : 'border-green-500/40 text-green-300 hover:bg-green-500/10'}`}
          >
            {emLaco ? <><Square className="w-3 h-3" /> Desligar</> : <><Play className="w-3 h-3" /> Ligar</>}
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-2 mt-3">
          <label className="flex items-center gap-1.5 text-[11px] text-ink-2">
            rodar a cada
            <input
              value={intervalo}
              onChange={e => setIntervalo(e.target.value.replace(/\D/g, ''))}
              disabled={emLaco}
              inputMode="numeric"
              className="w-14 bg-surface-2 border border-line rounded-md px-2 py-1 text-[11px] text-ink-1 text-center disabled:opacity-40"
            />
            min
          </label>
          <span className="text-[10px] text-ink-4">mínimo de 3 minutos, abaixo disso a estatística do provedor ainda não mudou</span>
        </div>

        {emLaco ? (
          <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2">
            {[
              { l: 'Rodadas', v: String(watch?.rodadas ?? 0) },
              { l: 'Desde',   v: horaCurta(watch?.iniciado_em) || '-' },
              { l: 'Última',  v: horaCurta(watch?.ultima_rodada) || 'primeira em curso' },
              {
                l: 'Próxima em',
                v: watch?.proxima_rodada_em == null ? 'rodando'
                   : watch.proxima_rodada_em <= 0 ? 'agora'
                   : `${Math.ceil(watch.proxima_rodada_em / 60)} min`,
              },
            ].map(x => (
              <div key={x.l} className="bg-surface-0 rounded-md px-3 py-2 border border-line">
                <div className="font-mono text-sm font-bold text-ink-1 truncate">{x.v}</div>
                <div className="text-[10px] text-ink-4">{x.l}</div>
              </div>
            ))}
          </div>
        ) : watch?.motivo_parada ? (
          /* Um laço que parou sem ninguém mandar parar é a informação mais
             importante desta tela · sem isto, o painel só voltava a mostrar o
             botão "Ligar" e a queda passava como se nunca tivesse acontecido. */
          <p className="mt-3 text-[11px] text-amber-300 leading-relaxed flex items-start gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px" />
            Parou depois de {watch.rodadas} rodada(s), {watch.motivo_parada}
          </p>
        ) : null}

        <p className="mt-3 text-[10px] text-ink-4 leading-relaxed">
          O laço vive dentro do processo do site. Um deploy ou um restart do serviço derruba ele,
          e o painel volta a mostrar &quot;Ligar&quot;. Fechar esta página não desliga nada.
        </p>
      </div>

      {/* ── Disparo ───────────────────────────────────────────────────────── */}
      <div className="bg-surface-1 border border-line rounded-lg p-4">
        <h3 className="text-xs font-semibold text-ink-3 mb-3">Rodada avulsa</h3>
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
            disabled={rodando || emLaco}
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
            {run.started_at && <>início {horaCurta(run.started_at)}</>}
            {run.finished_at && <>, fim {horaCurta(run.finished_at)}</>}
            {run.returncode !== null && (
              <span className={run.returncode === 0 ? ' text-green-400' : ' text-red-400'}>
                {' '}, saída {run.returncode}
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
            {stats.greens}G, {stats.reds}R, {stats.push}P em {stats.resolvidos} resolvidos,
            {' '}e {stats.expirados} tiveram a janela da odd fechada antes de alguém pegar
            {stats.minuto_medio !== null && <>, com minuto médio de entrada {stats.minuto_medio}&#39;</>}
          </p>
        </div>
      )}

      {/* ── Picks da rodada ───────────────────────────────────────────────── */}
      <div className="bg-surface-1 border border-line rounded-lg p-4">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <h3 className="text-xs font-semibold text-ink-3">
            Picks gerados {picks.length > 0 && <span className="text-ink-4 font-normal">, {picks.length}</span>}
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
                  {diaMes(p.match_date)}, {p.minute_at_creation}&#39;, odd {Number(p.odd).toFixed(2)}
                  {p.ev !== null && p.ev !== undefined && <>. EV {(Number(p.ev) * 100).toFixed(1)}%</>}
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
                      {p.ev !== null && p.ev !== undefined ? `${(Number(p.ev) * 100).toFixed(1)}%` : '-'}
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
