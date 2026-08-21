/*
 * Aba "Picks Ao Vivo" · as oportunidades que o Motor Live encontrou.
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
 * jogo. O card mostra os dois, e é essa distância que diz se a aposta ainda
 * faz sentido.
 *
 * DUAS COISAS QUE ESTA TELA APRENDEU RODANDO COM JOGO DE VERDADE (11/08)
 * ---------------------------------------------------------------------
 * 1. ODD VENCIDA NÃO É PICK ENCERRADO. A odd ao vivo vale 3 minutos, então
 *    três minutos depois de nascer todo card caía na seção "Encerrados" com
 *    um "Expirado antes de ser seguido" e o tratamento visual de coisa morta ·
 *    enquanto a partida seguia no 38'. O que venceu foi o PREÇO. O pick
 *    continua de pé, continua sendo acompanhado e continua entrando na
 *    assertividade do motor (routers/live_picks.py: EXPIRED também é
 *    liquidado). Encerrado é só o que tem `result`.
 * 2. O CARD NÃO REPETE A PROSA. O `reasoning` do motor descreve exatamente os
 *    mesmos números que os ladrilhos e as barras já mostram. Aberto por
 *    padrão, ele dobrava a altura do card e virava parede de texto no celular.
 *    Fica atrás de um "Por que este pick", que é onde quem quer conferir vai
 *    procurar.
 *
 * A validade da odd fica visível o tempo todo, em contagem regressiva. Odd ao
 * vivo evapora, e um pick sem prazo à vista convida o usuário a registrar uma
 * aposta que já não existe.
 */
import { forwardRef, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Radio, Timer, CheckCircle2, ChevronDown } from 'lucide-react'
import api from '../services/api'
import ApostaModal from './ApostaModal'
import { Badge, Button, EmptyState, ErrorState, LiveDot, ResultBadge, SkeletonPickGrid, StatTile } from './ui'
import { PICK_TYPE_BORDER } from '../utils/resultStyle'

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

/* Cabeçalho de seção na mesma marcação de Picks.tsx (barra colorida + título).
   Duplicado aqui, e não importado, porque lá ele é interno da página · são dez
   linhas de marcação, e transformar em primitivo compartilhado mexeria nas 14
   chamadas daquele arquivo por um ganho que não é deste trabalho. */
function TituloDeSecao({ cor, texto }: { cor: string; texto: string }) {
  return (
    <div className="flex items-center gap-3 mb-4 mt-6 first:mt-0">
      <span className={`w-0.5 h-5 ${cor} rounded-full block`} />
      <h2 className="text-sm font-bold text-ink-2">{texto}</h2>
    </div>
  )
}

function TeamLogo({ id, name }: { id?: number; name: string }) {
  const src = TEAM_LOGO(id)
  if (!src) return null
  return (
    <img src={src} alt={name} width={18} height={18}
      className="object-contain shrink-0" style={{ width: 18, height: 18 }}
      onError={e => (e.currentTarget.style.display = 'none')} />
  )
}

/* Barra do progresso da linha: onde a linha está, onde o jogo está e de que
   lado o pick precisa ficar.

   Os dois rótulos ficam ACIMA da barra, um em cada ponta, em vez de flutuarem
   colados nas posições exatas: com linha 10 e valor 5 eles se sobrepunham, e
   um número em cima do outro não informa nada. A posição continua sendo dada
   pelo desenho · o texto só nomeia. */
function BarraDaLinha({ atual, linha, direcao, rotulo }: {
  atual: number; linha: number; direcao: 'over' | 'under'; rotulo?: string
}) {
  const maximo = Math.max(linha * 1.6, atual * 1.15 + 1)
  const posLinha = Math.min((linha / maximo) * 100, 97)
  const posAtual = Math.min((atual / maximo) * 100, 100)
  const favoravel = direcao === 'over' ? atual > linha : atual < linha
  const cor = favoravel ? 'bg-green-500' : 'bg-red-400'

  return (
    <div className="mt-3">
      <div className="flex items-baseline justify-between text-[10px] text-ink-4 mb-1.5">
        <span>
          {rotulo ?? 'agora'}{' '}
          <span className={`font-bold tabular-nums ${favoravel ? 'text-green-400' : 'text-red-400'}`}>
            {atual}
          </span>
        </span>
        <span>linha <span className="font-bold text-ink-2 tabular-nums">{linha}</span></span>
      </div>
      <div className="relative h-1.5 bg-surface-3/60 rounded-full">
        <div className={`absolute left-0 top-0 h-full rounded-full transition-all duration-700 ${cor}`}
          style={{ width: `${posAtual}%` }} />
        <div className="absolute top-1/2 -translate-y-1/2 w-px h-3 bg-ink-2/70 rounded"
          style={{ left: `${posLinha}%` }} />
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
      <div className="flex items-baseline justify-between text-[10px] text-ink-4 mb-1.5">
        <span>Pressão ofensiva</span>
        <span className="tabular-nums">
          {casa.toFixed(2)} {PRESSAO_LABEL[nivelPressao(casa) ?? ''] ?? ''}
          {' · '}
          {fora.toFixed(2)} {PRESSAO_LABEL[nivelPressao(fora) ?? ''] ?? ''}
        </span>
      </div>
      <div className="flex h-1.5 rounded-full overflow-hidden bg-surface-3/60">
        <div className="bg-accent/70 transition-all duration-700" style={{ width: `${fatiaCasa}%` }} />
        <div className="bg-ink-4/40 transition-all duration-700" style={{ width: `${100 - fatiaCasa}%` }} />
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
      {expirou
        ? 'preço da criação · confira na casa'
        : `odd válida por ${Math.floor(restante / 60)}:${String(restante % 60).padStart(2, '0')}`}
    </span>
  )
}

const CardLive = forwardRef<HTMLDivElement, {
  pick: LivePick
  onSeguir: (p: LivePick) => void
}>(function CardLive({ pick, onSeguir }, ref) {
  /* Encerrado é só o que tem resultado. `EXPIRED` sem resultado quer dizer que
     a JANELA DA ODD fechou sem ninguém seguir · o jogo continua e o pick
     continua sendo acompanhado (ver o cabeçalho deste arquivo). */
  const encerrado = !!pick.result
  const oddVencida = pick.status === 'EXPIRED' && !pick.result
  const direcao: 'over' | 'under' = pick.line.toLowerCase().startsWith('under') ? 'under' : 'over'
  const linhaNum = parseFloat(pick.line.replace(/[^\d.]/g, ''))
  const temBarra = pick.current_val != null && !isNaN(linhaNum)
  const podeSeguir = !pick.is_followed && !encerrado && !oddVencida

  return (
    <motion.div
      ref={ref}
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={`pick-card p-3.5 ${PICK_TYPE_BORDER.live} ${encerrado ? 'opacity-75' : ''}`}
    >
      {/* cabeçalho: liga, jogo e minuto */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {pick.league_name && (
            <p className="text-[11px] text-ink-4 truncate mb-1">{pick.league_name}</p>
          )}
          <div className="flex items-center gap-2 text-sm font-bold text-ink-1">
            <TeamLogo id={pick.home_team_id} name={pick.home_team_name} />
            <span className="truncate">{pick.home_team_name}</span>
            <span className="text-ink-3 font-black tabular-nums px-0.5">
              {pick.home_goals ?? '-'}<span className="text-ink-4">x</span>{pick.away_goals ?? '-'}
            </span>
            <span className="truncate">{pick.away_team_name}</span>
            <TeamLogo id={pick.away_team_id} name={pick.away_team_name} />
          </div>
        </div>
        <div className="shrink-0">
          {pick.is_live ? (
            <Badge tone="red" className="gap-1.5">
              <LiveDot tone="red" className="w-1.5 h-1.5" />
              {pick.elapsed != null ? `${pick.elapsed}'` : STATUS_LABEL[pick.live_status] ?? pick.live_status}
            </Badge>
          ) : (
            <Badge tone="neutral">{STATUS_LABEL[pick.live_status] ?? pick.live_status}</Badge>
          )}
        </div>
      </div>

      {/* a aposta */}
      <div className="flex items-end justify-between gap-3 mt-3 pt-3 border-t border-line">
        <div className="min-w-0">
          <p className="text-[10px] text-ink-4 uppercase tracking-wide font-bold">{pick.market}</p>
          <p className="text-base font-black text-ink-1 truncate leading-tight">{pick.line}</p>
        </div>
        <div className="text-right shrink-0">
          <p className="text-[10px] text-ink-4 uppercase tracking-wide font-bold">Odd</p>
          <p className="text-xl font-black text-accent tabular-nums leading-tight">
            {Number(pick.odd).toFixed(2)}
          </p>
        </div>
      </div>

      {temBarra && (
        <BarraDaLinha atual={Number(pick.current_val)} linha={linhaNum} direcao={direcao}
          rotulo={pick.stat_label?.toLowerCase()} />
      )}

      {/* números do motor · ladrilhos do sistema, não caixas próprias */}
      <div className="grid grid-cols-3 gap-2 mt-3">
        <StatTile className="p-2" label="Probabilidade"
          value={<span className="text-lg">{(pick.probability * 100).toFixed(0)}%</span>} />
        <StatTile className="p-2" label="EV" tone={pick.ev >= 0 ? 'green' : 'red'}
          value={<span className="text-lg">{pick.ev >= 0 ? '+' : ''}{(pick.ev * 100).toFixed(1)}%</span>} />
        <StatTile className="p-2" label="Confiança"
          value={<span className="text-lg">{(pick.confidence * 100).toFixed(0)}%</span>} />
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

      <div className="flex flex-wrap gap-x-3 gap-y-1 mt-3 text-[11px] text-ink-4">
        <span>
          Criado aos <span className="font-bold text-ink-2 tabular-nums">{pick.minute_at_creation}&#39;</span>
          {' · '}{pick.home_goals_at_creation}x{pick.away_goals_at_creation}
          {' · '}<span className="tabular-nums">{pick.observed_at_creation}</span>{' '}
          {pick.stat_label?.toLowerCase() ?? 'no mercado'}
        </span>
        {pick.rhythm_level && (
          <span>
            Ritmo <span className="font-bold text-ink-2">
              {RITMO_LABEL[pick.rhythm_level] ?? pick.rhythm_level.toLowerCase()}
            </span>
            {pick.rhythm_trend && pick.rhythm_trend !== 'INDEFINIDA' && (
              <span className={
                pick.rhythm_trend === 'ACELERANDO' ? ' text-green-400'
                  : pick.rhythm_trend === 'DESACELERANDO' ? ' text-amber-400' : ''}>
                {' '}{TENDENCIA_LABEL[pick.rhythm_trend] ?? pick.rhythm_trend.toLowerCase()}
              </span>
            )}
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
        {pick.data_freshness && pick.data_freshness !== 'FRESH' && (
          <span className="text-amber-400">dado {pick.data_freshness.toLowerCase()}</span>
        )}
      </div>

      {/* A prosa do motor repete os números acima · fica atrás de um toque, em
          vez de dobrar a altura do card com o que já está na tela. */}
      {pick.reasoning && (
        <details className="group mt-3">
          <summary className="flex items-center gap-1 text-[11px] font-bold text-ink-3 cursor-pointer
                              list-none hover:text-ink-2 transition-colors">
            <ChevronDown size={12} className="transition-transform group-open:rotate-180" />
            Por que este pick
          </summary>
          <p className="mt-2 text-[11px] text-ink-3 leading-relaxed">{pick.reasoning}</p>
        </details>
      )}

      {/* rodapé: validade e ação */}
      <div className="flex items-center justify-between gap-3 mt-3 pt-3 border-t border-line">
        {encerrado ? (
          <span className="inline-flex items-center gap-2">
            <ResultBadge result={pick.result} />
            {pick.profit != null && (
              <span className={`text-[11px] font-bold tabular-nums ${
                Number(pick.profit) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {Number(pick.profit) >= 0 ? '+' : ''}{Number(pick.profit).toFixed(2)}u
              </span>
            )}
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
})

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

  /* O corte é pelo RESULTADO, não pelo status. Odd vencida não encerra pick:
     ele segue sendo acompanhado e liquidado como qualquer outro (ver o
     cabeçalho deste arquivo). Cortar por status mandava pra "Encerrados" um
     pick de um jogo que ainda estava no 38'. */
  const emAndamento = useMemo(() => (picks ?? []).filter(p => !p.result), [picks])
  const encerrados = useMemo(() => (picks ?? []).filter(p => !!p.result), [picks])

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
    <div>
      {/* Painel de abertura na cor do produto, como o das outras abas · o Live
          é vermelho no site inteiro (PICK_TYPE_HEX.live). */}
      <div className="bg-red-500/5 border border-red-400/25 rounded-lg p-4 mb-6">
        <h3 className="text-sm font-bold text-red-300 mb-2 flex items-center gap-2">
          <LiveDot tone="red" />
          O que são os Picks Ao Vivo?
        </h3>
        <p className="text-[13px] text-ink-3 leading-relaxed">
          O motor lê o placar, o ritmo e as estatísticas da partida{' '}
          <span className="font-bold text-ink-2">em andamento</span> e compara com a odd do momento.
          Ele só publica quando o jogo se afasta do esperado e o preço paga por isso, então
          varredura sem oportunidade não vira pick.
        </p>
        <p className="text-[13px] text-ink-3 leading-relaxed mt-2">
          A odd ao vivo muda rápido: o preço mostrado é o do instante da análise.{' '}
          <span className="font-bold text-ink-2">Confira o valor na casa antes de apostar.</span>
        </p>
      </div>

      {emAndamento.length === 0 && encerrados.length === 0 && (
        <EmptyState
          Icon={Radio}
          title="Nenhuma oportunidade ao vivo agora"
          description="O motor só publica quando o jogo se afasta do esperado e a odd paga por isso. Sem oportunidade, nada é publicado."
        />
      )}

      {emAndamento.length > 0 && (
        <>
          <TituloDeSecao cor="bg-red-400" texto={`Em andamento · ${emAndamento.length}`} />
          <div className="space-y-4">
            <AnimatePresence mode="popLayout">
              {emAndamento.map(p => (
                <CardLive key={p.id} pick={p} onSeguir={setAlvo} />
              ))}
            </AnimatePresence>
          </div>
        </>
      )}

      {encerrados.length > 0 && (
        <>
          <TituloDeSecao cor="bg-line-strong" texto={`Encerrados · ${encerrados.length}`} />
          <div className="space-y-4">
            <AnimatePresence mode="popLayout">
              {encerrados.map(p => (
                <CardLive key={p.id} pick={p} onSeguir={setAlvo} />
              ))}
            </AnimatePresence>
          </div>
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
