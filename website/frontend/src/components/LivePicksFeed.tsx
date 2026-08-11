/*
 * Aba "Ao Vivo" · as oportunidades que o Motor Live encontrou.
 *
 * NÃO CONFUNDIR COM LivePicks.tsx
 * -------------------------------
 * `LivePicks.tsx` é "Minhas Apostas": o que o usuário decidiu seguir, sendo
 * acompanhado em tempo real. Este arquivo é o produto novo: o que o motor
 * está sugerindo agora. São telas diferentes com dados diferentes, e a
 * colisão de nome que existia na chave da aba (`aovivo` significando Minhas
 * Apostas) foi desfeita junto com este componente.
 *
 * O QUE O CARD MOSTRA, E POR QUÊ
 * ------------------------------
 * Um pick Live carrega duas leituras do mesmo jogo, e as duas importam:
 *   - o SNAPSHOT da criação, que é o que o motor viu quando decidiu;
 *   - o ESTADO ATUAL, que é onde o jogo está agora.
 * Mostrar só o segundo esconde a análise; mostrar só o primeiro mente sobre o
 * jogo. O card mostra os dois lado a lado, e é essa distância que diz se a
 * aposta ainda faz sentido.
 *
 * A validade da odd fica visível o tempo todo, em contagem regressiva. Odd ao
 * vivo evapora, e um pick sem prazo à vista convida o usuário a registrar uma
 * aposta que já não existe.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Radio, TrendingUp, Timer, CheckCircle2, Ban } from 'lucide-react'
import api from '../services/api'
import ApostaModal from './ApostaModal'
import { Button, EmptyState, ErrorState, SkeletonPickGrid } from './ui'
import { getResultStyle, PICK_TYPE_BORDER } from '../utils/resultStyle'

const TEAM_LOGO = (id?: number) => (id ? `/api/proxy/team/${id}.png` : null)

/* Mesmo intervalo do polling de Minhas Apostas (15s): o dado que alimenta os
   dois vem do mesmo cache de 20s no backend, então poll mais rápido só
   gastaria requisição sem trazer número novo. */
const POLL_MS = 15000

const STATUS_LABEL: Record<string, string> = {
  '1H': '1º Tempo', HT: 'Intervalo', '2H': '2º Tempo', ET: 'Prorrogação',
  FT: 'Encerrado', AET: 'Encerrado', PEN: 'Encerrado', NS: 'Não iniciado',
}

interface LivePick {
  id: number
  fixture_id: number
  league_name?: string
  home_team_name: string
  away_team_name: string
  home_team_id?: number
  away_team_id?: number
  market: string
  market_type: string
  line: string
  odd: number
  probability: number
  ev: number
  edge: number
  confidence: number
  stake_units?: number
  reasoning?: string
  minute_at_creation: number
  home_goals_at_creation: number
  away_goals_at_creation: number
  corners_at_creation?: number | null
  shots_at_creation?: number | null
  shots_on_target_at_creation?: number | null
  possession_home_at_creation?: number | null
  observed_at_creation: number
  remaining_minutes: number
  /* leituras do motor no instante da criação */
  pressure_home?: number | null
  pressure_away?: number | null
  pressure_total?: number | null
  rhythm_score?: number | null
  rhythm_level?: string | null
  rhythm_trend?: string | null
  live_signal_score?: number | null
  data_freshness?: string | null
  projected_total?: number | null
  odd_valid_until?: string
  segundos_de_validade: number | null
  status: string
  expiration_reason?: string
  result?: string | null
  profit?: number | null
  /* estado atual, vindo do enriquecimento no backend */
  live_status: string
  elapsed?: number | null
  home_goals?: number | null
  away_goals?: number | null
  current_val?: number | null
  stat_label?: string
  is_live: boolean
  is_ft: boolean
  pick_status?: string
  is_followed: boolean
  user_stake_units?: number | null
}

function TeamLogo({ id, name }: { id?: number; name: string }) {
  const src = TEAM_LOGO(id)
  if (!src) return null
  return (
    <img src={src} alt={name} width={20} height={20}
      className="object-contain shrink-0" style={{ width: 20, height: 20 }}
      onError={e => (e.currentTarget.style.display = 'none')} />
  )
}

/* Barra do progresso da linha. Mesma leitura visual da barra de Minhas
   Apostas, reduzida ao essencial: onde a linha está, onde o jogo está e de
   que lado o pick precisa ficar. */
function BarraDaLinha({ atual, linha, direcao }: {
  atual: number; linha: number; direcao: 'over' | 'under'
}) {
  const maximo = Math.max(linha * 1.7, atual * 1.1 + 1)
  const posLinha = Math.min((linha / maximo) * 100, 98)
  const posAtual = Math.min((atual / maximo) * 100, 100)
  const ganhando = direcao === 'over' ? atual > linha : atual < linha
  const cor = ganhando ? '#22c55e' : '#ef4444'
  return (
    <div className="relative h-1.5 bg-surface-3/60 rounded-full mt-5 mb-6">
      <div className="absolute left-0 top-0 h-full rounded-full transition-all duration-700"
        style={{ width: `${posAtual}%`, backgroundColor: cor }} />
      <div className="absolute top-1/2 -translate-y-1/2 w-px h-3 bg-white/50 rounded"
        style={{ left: `${posLinha}%` }} />
      <div className="absolute -top-5 text-[10px] font-black text-ink-3"
        style={{ left: `${posLinha}%`, transform: 'translateX(-50%)' }}>
        linha {linha}
      </div>
      <div className="absolute -bottom-5 text-[10px] font-black"
        style={{ left: `${Math.min(posAtual, 92)}%`, transform: 'translateX(-50%)', color: cor }}>
        {atual}
      </div>
    </div>
  )
}

const RITMO_LABEL: Record<string, string> = {
  BAIXO: 'baixo', MEDIO: 'médio', ALTO: 'alto', MUITO_ALTO: 'muito alto',
}
const TENDENCIA_LABEL: Record<string, string> = {
  ACELERANDO: 'acelerando', DESACELERANDO: 'desacelerando',
  ESTAVEL: 'estável', INDEFINIDA: 'sem leitura',
}
const PRESSAO_LABEL: Record<string, string> = {
  BAIXA: 'baixa', MEDIA: 'média', ALTA: 'alta', MUITO_ALTA: 'muito alta',
}

/* Nível da pressão a partir do score. Os cortes são os mesmos de
   pressure_model.py (escala centrada em 0.5 = time médio) · duplicar o número
   aqui é aceitável porque é só rótulo de exibição, mas se o corte mudar lá,
   muda aqui. */
function nivelPressao(score?: number | null): string | null {
  if (score == null) return null
  if (score < 0.35) return 'BAIXA'
  if (score < 0.50) return 'MEDIA'
  if (score < 0.68) return 'ALTA'
  return 'MUITO_ALTA'
}

/* Barra de pressão dos dois lados. Mostra domínio, que é a pergunta que o
   número responde: quem está empurrando o jogo. */
function BarraPressao({ casa, fora, nomeCasa, nomeFora }: {
  casa: number; fora: number; nomeCasa: string; nomeFora: string
}) {
  const soma = casa + fora
  const fatiaCasa = soma > 0 ? (casa / soma) * 100 : 50
  return (
    <div className="mt-3">
      <div className="flex items-center justify-between text-[10px] font-bold text-ink-4 uppercase tracking-wide mb-1">
        <span>Pressão ofensiva</span>
        <span className="tabular-nums text-ink-3 normal-case">
          {casa.toFixed(2)} {PRESSAO_LABEL[nivelPressao(casa) ?? ''] ?? ''}
          {' · '}
          {fora.toFixed(2)} {PRESSAO_LABEL[nivelPressao(fora) ?? ''] ?? ''}
        </span>
      </div>
      <div className="flex h-1.5 rounded-full overflow-hidden bg-surface-3/60">
        <div className="bg-accent/70 transition-all duration-700" style={{ width: `${fatiaCasa}%` }} />
        <div className="bg-ink-4/50 transition-all duration-700" style={{ width: `${100 - fatiaCasa}%` }} />
      </div>
      <div className="flex items-center justify-between text-[10px] text-ink-4 mt-1">
        <span className="truncate max-w-[45%]">{nomeCasa}</span>
        <span className="truncate max-w-[45%] text-right">{nomeFora}</span>
      </div>
    </div>
  )
}

function Contagem({ segundos }: { segundos: number | null }) {
  const [restante, setRestante] = useState(segundos ?? 0)
  useEffect(() => { setRestante(segundos ?? 0) }, [segundos])
  useEffect(() => {
    if (restante <= 0) return
    const t = setInterval(() => setRestante(s => Math.max(0, s - 1)), 1000)
    return () => clearInterval(t)
  }, [restante > 0])

  if (segundos === null) return null
  const expirou = restante <= 0
  const apertado = restante > 0 && restante <= 30
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] font-bold tabular-nums ${
      expirou ? 'text-ink-4' : apertado ? 'text-amber-400' : 'text-ink-3'}`}>
      <Timer size={11} />
      {expirou ? 'odd vencida' : `odd válida por ${Math.floor(restante / 60)}:${String(restante % 60).padStart(2, '0')}`}
    </span>
  )
}

function CardLive({ pick, onSeguir }: {
  pick: LivePick
  onSeguir: (p: LivePick) => void
}) {
  const resultado = getResultStyle(pick.result)
  const expirado = pick.status === 'EXPIRED' && !pick.result
  const direcao: 'over' | 'under' = pick.line.toLowerCase().startsWith('under') ? 'under' : 'over'
  const linhaNum = parseFloat(pick.line.replace(/[^\d.]/g, ''))
  const temBarra = pick.current_val != null && !isNaN(linhaNum)
  const podeSeguir = !pick.is_followed && !pick.result && !expirado
  const evoluiu = pick.current_val != null && pick.current_val !== pick.observed_at_creation

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={`pick-card ${PICK_TYPE_BORDER.live} ${expirado ? 'opacity-60' : ''}`}
    >
      {/* cabeçalho: jogo e minuto */}
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-[11px] text-ink-4 mb-1.5">
            {pick.league_name && <span className="truncate">{pick.league_name}</span>}
          </div>
          <div className="flex items-center gap-2 text-sm font-bold text-ink-1">
            <TeamLogo id={pick.home_team_id} name={pick.home_team_name} />
            <span className="truncate">{pick.home_team_name}</span>
            <span className="text-ink-4 font-black tabular-nums px-1">
              {pick.home_goals ?? '-'} x {pick.away_goals ?? '-'}
            </span>
            <span className="truncate">{pick.away_team_name}</span>
            <TeamLogo id={pick.away_team_id} name={pick.away_team_name} />
          </div>
        </div>
        <div className="shrink-0 text-right">
          {pick.is_live ? (
            <span className="inline-flex items-center gap-1.5 text-[11px] font-black text-red-300 bg-red-500/10 border border-red-400/25 rounded px-2 py-0.5">
              <span className="relative inline-flex w-1.5 h-1.5">
                <span className="absolute inset-0 rounded-full bg-red-400 opacity-60 animate-ping" />
                <span className="relative inline-flex w-1.5 h-1.5 rounded-full bg-red-400" />
              </span>
              {pick.elapsed != null ? `${pick.elapsed}'` : STATUS_LABEL[pick.live_status] ?? pick.live_status}
            </span>
          ) : (
            <span className="text-[11px] font-bold text-ink-4">
              {STATUS_LABEL[pick.live_status] ?? pick.live_status}
            </span>
          )}
        </div>
      </div>

      {/* a aposta */}
      <div className="flex items-center justify-between gap-3 py-2.5 border-y border-line">
        <div className="min-w-0">
          <p className="text-[11px] text-ink-4 uppercase tracking-wide font-bold">{pick.market}</p>
          <p className="text-base font-black text-ink-1 truncate">{pick.line}</p>
        </div>
        <div className="text-right shrink-0">
          <p className="text-[10px] text-ink-4 uppercase tracking-wide font-bold">Odd</p>
          <p className="text-lg font-black text-accent tabular-nums">{Number(pick.odd).toFixed(2)}</p>
        </div>
      </div>

      {temBarra && <BarraDaLinha atual={Number(pick.current_val)} linha={linhaNum} direcao={direcao} />}

      {/* números do motor */}
      <div className="grid grid-cols-3 gap-2 mt-3">
        <div className="bg-surface-2/60 rounded-md px-2 py-1.5 text-center">
          <p className="text-[9px] text-ink-4 uppercase tracking-wide font-bold">Probabilidade</p>
          <p className="text-sm font-black text-ink-1 tabular-nums">{(pick.probability * 100).toFixed(0)}%</p>
        </div>
        <div className="bg-surface-2/60 rounded-md px-2 py-1.5 text-center">
          <p className="text-[9px] text-ink-4 uppercase tracking-wide font-bold">EV</p>
          <p className={`text-sm font-black tabular-nums ${pick.ev >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {pick.ev >= 0 ? '+' : ''}{(pick.ev * 100).toFixed(1)}%
          </p>
        </div>
        <div className="bg-surface-2/60 rounded-md px-2 py-1.5 text-center">
          <p className="text-[9px] text-ink-4 uppercase tracking-wide font-bold">Confiança</p>
          <p className="text-sm font-black text-ink-1 tabular-nums">{(pick.confidence * 100).toFixed(0)}%</p>
        </div>
      </div>

      {/* Pressão e ritmo · é o que separa este card de um card pré-jogo.
          Fica no corpo, não escondido no detalhe: é a leitura que justifica
          o pick ter nascido neste minuto e não em outro. */}
      {pick.pressure_home != null && pick.pressure_away != null && (
        <BarraPressao
          casa={Number(pick.pressure_home)} fora={Number(pick.pressure_away)}
          nomeCasa={pick.home_team_name} nomeFora={pick.away_team_name}
        />
      )}

      <div className="flex flex-wrap gap-x-3 gap-y-1 mt-3 text-[11px] text-ink-3">
        {pick.rhythm_level && (
          <span>
            Ritmo <span className="font-bold text-ink-2">{RITMO_LABEL[pick.rhythm_level] ?? pick.rhythm_level.toLowerCase()}</span>
          </span>
        )}
        {pick.rhythm_trend && pick.rhythm_trend !== 'INDEFINIDA' && (
          <span>
            Tendência{' '}
            <span className={`font-bold ${
              pick.rhythm_trend === 'ACELERANDO' ? 'text-green-400'
                : pick.rhythm_trend === 'DESACELERANDO' ? 'text-amber-400' : 'text-ink-2'}`}>
              {TENDENCIA_LABEL[pick.rhythm_trend] ?? pick.rhythm_trend.toLowerCase()}
            </span>
          </span>
        )}
        {pick.live_signal_score != null && (
          <span>
            Sinais <span className="font-bold text-ink-2 tabular-nums">
              {(Number(pick.live_signal_score) * 100).toFixed(0)}%
            </span>
          </span>
        )}
        {pick.projected_total != null && (
          <span>
            Projeção <span className="font-bold text-ink-2 tabular-nums">
              {Number(pick.projected_total).toFixed(1)}
            </span>
          </span>
        )}
      </div>

      {/* O que o motor viu quando decidiu. O snapshot da criação nunca muda;
          "agora" ao lado mostra o quanto o jogo andou desde então. */}
      <div className="mt-3 text-[11px] text-ink-3 bg-surface-2/40 border border-line rounded-md px-2.5 py-2 leading-relaxed">
        <span className="font-bold text-ink-2">Criado aos {pick.minute_at_creation}&#39;</span>
        {' · '}placar {pick.home_goals_at_creation}x{pick.away_goals_at_creation}
        {' · '}{pick.observed_at_creation} {pick.stat_label?.toLowerCase() ?? 'no mercado'}
        {evoluiu && (
          <span className="text-ink-2"> · agora {pick.current_val}</span>
        )}
        {pick.shots_at_creation != null && (
          <>
            {' · '}{pick.shots_at_creation} finalizações
            {pick.shots_on_target_at_creation != null && ` (${pick.shots_on_target_at_creation} no alvo)`}
          </>
        )}
        {pick.data_freshness && pick.data_freshness !== 'FRESH' && (
          <span className="text-amber-400"> · dado {pick.data_freshness.toLowerCase()}</span>
        )}
      </div>

      {pick.reasoning && (
        <p className="mt-2 text-[11px] text-ink-3 leading-relaxed">{pick.reasoning}</p>
      )}

      {/* rodapé: validade e ação */}
      <div className="flex items-center justify-between gap-3 mt-3 pt-3 border-t border-line">
        {resultado ? (
          <span className={`text-[11px] font-black px-2 py-0.5 rounded border ${resultado.bg} ${resultado.border} ${resultado.text}`}>
            {resultado.label}
            {pick.profit != null && (
              <span className="ml-1.5 tabular-nums">
                {Number(pick.profit) >= 0 ? '+' : ''}{Number(pick.profit).toFixed(2)}u
              </span>
            )}
          </span>
        ) : expirado ? (
          <span className="inline-flex items-center gap-1 text-[11px] font-bold text-ink-4">
            <Ban size={11} /> Expirado antes de ser seguido
          </span>
        ) : (
          <Contagem segundos={pick.segundos_de_validade} />
        )}

        {pick.is_followed ? (
          <span className="inline-flex items-center gap-1 text-[11px] font-bold text-green-400">
            <CheckCircle2 size={12} />
            Em Minhas Apostas
            {pick.user_stake_units ? ` · ${pick.user_stake_units}u` : ''}
          </span>
        ) : podeSeguir ? (
          <Button size="sm" onClick={() => onSeguir(pick)}>Apostar</Button>
        ) : null}
      </div>
    </motion.div>
  )
}

export default function LivePicksFeed({ isActive }: {
  isActive: boolean
}) {
  const [picks, setPicks] = useState<LivePick[] | null>(null)
  const [disponivel, setDisponivel] = useState(true)
  const [motivo, setMotivo] = useState<string | null>(null)
  const [erro, setErro] = useState(false)
  const [alvo, setAlvo] = useState<LivePick | null>(null)
  const [salvando, setSalvando] = useState(false)
  const [erroModal, setErroModal] = useState<string | null>(null)
  const timer = useRef<number | null>(null)

  const carregar = useCallback(async () => {
    try {
      const r = await api.get('/live-picks/feed')
      setDisponivel(r.data.disponivel !== false)
      setMotivo(r.data.motivo ?? null)
      setPicks(r.data.picks ?? [])
      setErro(false)
    } catch {
      setErro(true)
      setPicks([])
    }
  }, [])

  /* Poll só enquanto a aba está visível. Fora dela não há motivo pra manter
     a chamada de pé: o backend consulta a API-Football nesse caminho. */
  useEffect(() => {
    if (!isActive) {
      if (timer.current) { clearInterval(timer.current); timer.current = null }
      return
    }
    carregar()
    timer.current = window.setInterval(carregar, POLL_MS)
    return () => { if (timer.current) clearInterval(timer.current) }
  }, [isActive, carregar])

  const confirmar = async (oddReal: number, casa: string, unidades: number) => {
    if (!alvo) return
    setSalvando(true)
    setErroModal(null)
    try {
      await api.post('/banca/follow', {
        pick_id: alvo.id, pick_type: 'live',
        stake_units: unidades, actual_odd: oddReal, bet_house: casa,
      })
      setAlvo(null)
      carregar()
    } catch (e: any) {
      setErroModal(e?.response?.data?.detail ?? 'Não foi possível registrar agora.')
    } finally {
      setSalvando(false)
    }
  }

  const ativos = useMemo(() => (picks ?? []).filter(p => !p.result && p.status !== 'EXPIRED'), [picks])
  const encerrados = useMemo(() => (picks ?? []).filter(p => p.result || p.status === 'EXPIRED'), [picks])

  if (!isActive) return null

  if (picks === null) return <SkeletonPickGrid />

  if (erro) return <ErrorState onRetry={carregar} />

  if (!disponivel) {
    return (
      <EmptyState
        Icon={Radio}
        title="Motor Ao Vivo não está ativo neste ambiente"
        description={motivo ?? 'Os Picks Ao Vivo ainda estão em validação e rodam apenas no ambiente de testes.'}
      />
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2.5 bg-surface-1 border border-line rounded-lg px-3.5 py-3">
        <TrendingUp size={16} className="text-red-300 shrink-0 mt-0.5" />
        <div className="text-[12px] text-ink-3 leading-relaxed">
          <p className="font-bold text-ink-2 mb-0.5">Oportunidades encontradas durante o jogo</p>
          <p>
            O motor lê o placar, o ritmo e as estatísticas da partida em andamento e compara com a
            odd do momento. A odd ao vivo muda rápido: confira o valor na casa antes de apostar.
          </p>
        </div>
      </div>

      {ativos.length === 0 && encerrados.length === 0 && (
        <EmptyState
          Icon={Radio}
          title="Nenhuma oportunidade ao vivo agora"
          description="O motor só publica quando o jogo se afasta do esperado e a odd paga por isso. Sem oportunidade, nada é publicado."
        />
      )}

      <AnimatePresence mode="popLayout">
        {ativos.map(p => (
          <CardLive key={p.id} pick={p} onSeguir={setAlvo} />
        ))}
      </AnimatePresence>

      {encerrados.length > 0 && (
        <>
          <p className="text-[11px] uppercase tracking-wide font-bold text-ink-4 pt-2">
            Encerrados
          </p>
          <AnimatePresence mode="popLayout">
            {encerrados.map(p => (
              <CardLive key={p.id} pick={p} onSeguir={setAlvo} />
            ))}
          </AnimatePresence>
        </>
      )}

      <AnimatePresence>
        {alvo && (
          <ApostaModal
            pickOdd={Number(alvo.odd)}
            suggestedUnits={alvo.stake_units ?? 1}
            maxUnits={4}
            loading={salvando}
            error={erroModal}
            onConfirm={confirmar}
            onCancel={() => { setAlvo(null); setErroModal(null) }}
          />
        )}
      </AnimatePresence>
    </div>
  )
}
