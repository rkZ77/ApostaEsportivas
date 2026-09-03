import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Spinner } from './ui'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { X, TrendingUp, Activity, List, MessageCircle, Route, Lock, Share2, Sparkles } from 'lucide-react'
import { getResultStyle, PICK_TYPE_LABEL } from '../utils/resultStyle'
import api from '../services/api'
import { pctProb, fmtUnits } from '../utils/format'
import PickSocial from './PickSocial'
import { calcVipStake, calcFreeStake, calcMultiplaStake } from '../utils/stakeUtils'
import { translateMarket, translateLine, linhaDoJogador } from '../utils/marketTranslate'
import { PlayerPhoto } from './TeamLogo'
import { backdropFade, dialogScale } from '../lib/motion'
import { useShareStoryImage } from '../hooks/useShareStoryImage'
import AnalysisModal from './AnalysisModal'
import { AnimatePresence } from 'framer-motion'

interface RecentMatch {
  match_date: string; is_home: boolean; gf: number; ga: number
  corners_f: number; corners_a: number; resultado: string
  total_goals: number; home_team_id: number; away_team_id: number
}
interface OddRow {
  market_name: string; value_name: string; odd_value: number
  bookmaker_name: string; market_type: string; side_team: string
}

const TEAM_LOGO = (id?: number) => id ? `/api/proxy/team/${id}.png` : null

const resultColor: Record<string, string> = {
  W: 'bg-green-500 text-black',
  D: 'bg-surface-3 text-ink-1',
  L: 'bg-red-500 text-ink-1',
}

function FormBadge({ r }: { r: string }) {
  return (
    <span className={`w-7 h-7 flex items-center justify-center rounded-full text-xs font-black shrink-0 ${resultColor[r] ?? 'bg-surface-3 text-ink-1'}`}>
      {r}
    </span>
  )
}

export default function SuggestionDetail({ id, onClose, pickType = 'vip', banca }: {
  id: number; onClose: () => void; pickType?: string
  banca?: { bankroll_current: number; unit_value: number } | null
}) {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<string>('ia')
  const [standings, setStandings] = useState<any>(null)
  const [standingsLoading, setStandingsLoading] = useState(false)
  const [caminho, setCaminho] = useState<any[]>([])
  const [caminhoLoading, setCaminhoLoading] = useState(false)
  const [locked, setLocked] = useState(false)
  // Compartilhar e "Entenda esta analise" existiam so' no card da aba Hoje.
  // Quem chegava pelo historico (Meus Picks, Banca) via os mesmos dados sem as
  // duas acoes, entao o mesmo pick tinha dois comportamentos dependendo da
  // porta de entrada.
  const [showAnalysis, setShowAnalysis] = useState(false)
  const { share: shareStory, sharing, shared } = useShareStoryImage()

  useEffect(() => {
    setLoading(true); setData(null); setLocked(false); setTab('ia'); setStandings(null); setCaminho([])
    api.get(`/suggestions/${id}/detail`, { params: { pick_type: pickType } })
      .then(r => setData(r.data))
      .catch(err => { if (err?.response?.status === 403) setLocked(true) })
      .finally(() => setLoading(false))
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [id])

  useEffect(() => {
    if (tab !== 'standings' || standings || standingsLoading) return
    const fixtureId = data?.suggestion?.fixture_id
    if (!fixtureId) return
    setStandingsLoading(true)
    api.get(`/suggestions/${fixtureId}/standings`)
      .then(r => setStandings(r.data))
      .catch(() => setStandings({ groups: [] }))
      .finally(() => setStandingsLoading(false))
  }, [tab, data])

  useEffect(() => {
    if (tab !== 'caminho' || caminho.length > 0 || caminhoLoading) return
    setCaminhoLoading(true)
    api.get('/suggestions/alavancagem', { params: { limit: 50 } })
      .then(r => setCaminho(Array.isArray(r.data?.items) ? r.data.items : []))
      .catch(() => setCaminho([]))
      .finally(() => setCaminhoLoading(false))
  }, [tab])

  const isAlav = pickType === 'alavancagem'
  const hasStats = pickType === 'vip' || pickType === 'free' || isAlav
  // "Médias" saiu em 2026-08-14: as médias por time ja' vivem na aba Jogos,
  // com mais contexto e sem competir com a leitura do pick. Aqui elas
  // duplicavam a mesma informacao dentro do painel de decisao.
  const tabs = [
    { key: 'ia',         label: 'Pick',          Icon: TrendingUp    },
    ...(hasStats ? [
      { key: 'form',     label: 'Forma',         Icon: Activity      },
      ...(isAlav
        ? [{ key: 'caminho', label: 'Caminho', Icon: Route }]
        : [{ key: 'standings', label: 'Classificação', Icon: List }]
      ),
    ] : []),
    { key: 'social',     label: 'Chat',          Icon: MessageCircle },
  ]

  const s = data?.suggestion
  const homeLogo = TEAM_LOGO(s?.home_team_id)
  const awayLogo = TEAM_LOGO(s?.away_team_id)
  const resultStyle = getResultStyle(s?.result)
  /*
   * Probabilidade estimada, nao confianca.
   *
   * Sao campos DIFERENTES no banco: medido em picks_vip, confidence vem
   * sistematicamente acima de probability (0,816 contra 0,755 no mesmo pick).
   * Mostrar confidence sob o rotulo "probabilidade" seria anunciar 82% onde a
   * chance calculada e 75%.
   *
   * `confidence` so entra quando nao ha probabilidade: picks VIP antigos e
   * multiplas, que nao tem a coluna.
   */
  const probBruta = s?.probability ?? s?.confidence ?? 0
  const confidence = Math.round(Number(probBruta) * 100)
  const probAproximada = s?.probability == null
  const ev = s?.ev != null ? (Number(s.ev) * 100).toFixed(1) : null

  const stakeUnits = (() => {
    if (pickType === 'alavancagem') return null
    if (!s) return 1

    // 1. Stake real apostada pelo usuário (user_followed_picks)
    if (s.user_stake_units != null && s.user_stake_units > 0) {
      return s.user_stake_units
    }

    // 2. Sugestão calculada pelo backend com banca real
    if (s.suggested_stake_units != null && s.suggested_stake_units > 0) {
      return s.suggested_stake_units
    }

    // 3. Fallback com mesmas funções dos cards (por tipo de pick)
    const isMultipla = pickType === 'multipla'
    const isFree     = pickType === 'free'
    const odd  = Number(s.total_odd ?? s.odd ?? 0)
    const prob = Number(s.probability ?? s.confidence ?? s.prob_real ?? 0)
    const ev   = Number(s.ev ?? 0)

    if (prob > 0 && odd > 1 && banca?.bankroll_current && banca.unit_value > 0) {
      if (isMultipla) {
        const sug = calcMultiplaStake(prob, odd, banca.bankroll_current, banca.unit_value)
        if (sug) return sug.units
      } else if (isFree) {
        const sug = calcFreeStake(prob, odd, ev, banca.bankroll_current, banca.unit_value)
        if (sug) return sug.units
      } else {
        const sug = calcVipStake(prob, odd, ev, banca.bankroll_current, banca.unit_value, s.stake_pct)
        if (sug) return sug.units
      }
    }

    // 4. Sem banca: escala de referência (1% banca ref. R$1000 = 1u)
    if (s.stake_pct) return Math.max(1, Math.round(s.stake_pct / 0.01))

    return 1
  })()

  return (
    <>
    <motion.div
      variants={backdropFade}
      initial="hidden"
      animate="visible"
      exit="exit"
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 backdrop-blur-sm sm:p-4"
      onClick={onClose}
    >
      {/* Modal no meio da tela, nao gaveta lateral · o pedido era abrir igual
          ao card da aba Hoje. No celular continua ocupando a tela inteira,
          que e o unico jeito de caber. */}
      <motion.div
        variants={dialogScale}
        className="w-full h-full sm:h-auto sm:max-h-[90dvh] sm:max-w-lg bg-surface-0 sm:border border-line sm:rounded-lg flex flex-col overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        <div className="shrink-0 border-b border-line">
          {/* Times */}
          <div className="px-5 pt-4 pb-3">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs text-ink-3 font-semibold">
                {/* PICK_TYPE_LABEL cobre os seis pipelines. A cadeia de
                    ternarios que estava aqui terminava em 'VIP', entao um
                    pick de faltas abria rotulado como VIP. */}
                {pickType === 'free' ? 'Dica do Dia' : PICK_TYPE_LABEL[pickType] ?? 'VIP'}
              </span>
              <button
                onClick={onClose}
                className="flex items-center gap-1.5 text-xs font-bold text-ink-2 hover:text-ink-1 bg-surface-2 hover:bg-surface-3 border border-line-strong hover:border-ink-4 px-3 py-1.5 rounded-lg transition-colors"
              >
                <X className="w-3.5 h-3.5" />
                Fechar
              </button>
            </div>

            {s ? (
              <div className="flex items-center gap-3">
                {/* Casa */}
                <div className="flex-1 flex items-center gap-2 min-w-0">
                  {homeLogo && (
                    <img src={homeLogo} alt="" width={32} height={32} className="w-8 h-8 object-contain shrink-0"
                      onError={e => (e.currentTarget.style.display = 'none')} />
                  )}
                  <span className="font-black text-ink-1 text-sm leading-tight truncate">{s.home_team_name}</span>
                </div>

                {/* VS */}
                <div className="text-center shrink-0">
                  {resultStyle ? (
                    <span className={`text-xs font-black px-2 py-1 rounded-lg border ${resultStyle.bg} ${resultStyle.text} ${resultStyle.border}`}>
                      {resultStyle.label}
                    </span>
                  ) : (
                    <span className="text-ink-4 text-xs font-bold">VS</span>
                  )}
                  {s.match_datetime && (
                    <div className="text-[10px] text-ink-4 mt-1">
                      {new Date(s.match_datetime).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}
                    </div>
                  )}
                </div>

                {/* Visitante */}
                <div className="flex-1 flex items-center gap-2 justify-end min-w-0">
                  <span className="font-black text-ink-1 text-sm leading-tight truncate text-right">{s.away_team_name}</span>
                  {awayLogo && (
                    <img src={awayLogo} alt="" width={32} height={32} className="w-8 h-8 object-contain shrink-0"
                      onError={e => (e.currentTarget.style.display = 'none')} />
                  )}
                </div>
              </div>
            ) : (
              <div className="h-10 flex items-center">
                <Spinner size="lg" className="mx-auto" />
              </div>
            )}
          </div>

          {/* Bet summary bar */}
          {s && pickType !== 'multipla' && pickType !== 'alavancagem' && (
            <div className="flex items-center gap-0 border-t border-line/60 text-center divide-x divide-line/60">
              {/* JOGADOR, quando o pick é sobre uma pessoa (02/09).
                * Esta barra é o mesmo dado do card, e o card passou a mostrar
                * quem, qual mercado e qual linha em campos próprios. Sem esta
                * célula o painel continuava com o nome diluído dentro da
                * string da linha, e o mesmo pick tinha duas leituras. */}
              {s.player_name && (
                <div className="flex-1 py-2.5 px-3 min-w-0">
                  <div className="text-[10px] text-ink-3 mb-0.5">Jogador</div>
                  <div className="flex items-center justify-center gap-1.5 min-w-0">
                    <PlayerPhoto id={s.player_id} name={s.player_name} size={20} />
                    <span className="text-xs font-bold text-ink-1 truncate">{s.player_name}</span>
                  </div>
                </div>
              )}
              <div className="flex-1 py-2.5 px-3">
                <div className="text-[10px] text-ink-3 mb-0.5">Mercado</div>
                <div className="text-xs font-bold text-ink-1 truncate">{translateMarket(s.market) ?? ''}</div>
              </div>
              {s.line && (
                <div className="flex-1 py-2.5 px-3">
                  <div className="text-[10px] text-ink-3 mb-0.5">Linha</div>
                  <div className="text-xs font-bold text-ink-1">
                    {linhaDoJogador(s.line, s.line_value, s.player_name)}
                  </div>
                </div>
              )}
              <div className="flex-1 py-2.5 px-3">
                <div className="text-[10px] text-ink-3 mb-0.5">Odd</div>
                <div className="font-mono text-sm font-black text-green-400">{Number(s.odd).toFixed(2)}</div>
              </div>
              <div className="flex-1 py-2.5 px-3">
                <div className="text-[10px] text-ink-3 mb-0.5">Casa</div>
                <div className="text-xs font-bold text-ink-1 truncate">{s.bet_house}</div>
              </div>
            </div>
          )}
        </div>

        {/* A barra de abas (Forma, Classificacao, Chat) saiu: o painel existe
            pra mostrar O PICK, igual ao card da aba Hoje. Forma e Classificacao
            vivem dentro do "Entenda esta analise", que e onde se vai quando a
            pergunta e "por que". O Chat continua alcancavel no rodape -- ele so
            existe aqui, e tirar a aba sem mais nada o apagaria do site. */}

        <div className="flex-1 overflow-y-auto p-5">
          {loading ? (
            <div className="flex items-center justify-center h-40">
              <Spinner size="lg" />
            </div>
          ) : locked ? (
            <div className="flex flex-col items-center text-center py-10 gap-3">
              <Lock className="w-6 h-6 text-yellow-400" />
              <p className="text-ink-2 text-sm max-w-xs">
                A análise completa da IA fica disponível só para assinantes VIP.
              </p>
              <Link
                to="/planos"
                className="mt-1 px-4 py-2 rounded-lg bg-green-600 hover:bg-green-500 text-white text-sm font-bold transition-colors"
              >
                Assinar VIP
              </Link>
            </div>
          ) : !data ? (
            <p className="text-ink-3 text-center py-10">Erro ao carregar dados.</p>
          ) : (
            <>
              {tab === 'ia' && (
                <div className="space-y-4">
                  {/* Métricas principais */}
                  <div className="font-mono grid grid-cols-3 gap-2">
                    <div className="bg-surface-1 border border-line rounded-lg p-3 text-center">
                      <div className="text-[10px] text-ink-3 mb-1">Probabilidade</div>
                      <div className={`text-2xl font-black ${confidence >= 75 ? 'text-green-400' : confidence >= 60 ? 'text-yellow-400' : 'text-ink-2'}`}>
                        {confidence}%
                      </div>
                    </div>
                    <div className="bg-surface-1 border border-line rounded-lg p-3 text-center">
                      {isAlav ? (
                        <>
                          <div className="text-[10px] text-ink-3 mb-1">Tipo</div>
                          <div className="text-2xl font-black text-ink-1 capitalize">{s?.tipo ?? 'N/D'}</div>
                        </>
                      ) : (
                        <>
                          <div className="text-[10px] text-ink-3 mb-1">Stake</div>
                          {stakeUnits != null
                            ? <div className="text-2xl font-black text-ink-1">{stakeUnits}u</div>
                            : <div className="text-xs text-ink-3 mt-1">s/d</div>
                          }
                        </>
                      )}
                    </div>
                    <div className="bg-surface-1 border border-line rounded-lg p-3 text-center">
                      <div className="text-[10px] text-ink-3 mb-1">EV</div>
                      <div className={`text-2xl font-black ${ev && Number(ev) > 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {ev ? `${Number(ev) > 0 ? '+' : ''}${ev}%` : ''}
                      </div>
                    </div>
                  </div>

                  {/* Barra de probabilidade */}
                  <div>
                    <div className="flex justify-between text-xs text-ink-3 mb-1.5">
                      <span>Probabilidade{probAproximada ? ' estimada' : ''}</span>
                      <span className={confidence >= 75 ? 'text-green-400' : confidence >= 60 ? 'text-yellow-400' : 'text-ink-2'}>{confidence}%</span>
                    </div>
                    <div className="bg-surface-2 rounded-full h-2 overflow-hidden">
                      <div
                        className={`h-2 rounded-full transition-all duration-700 ${confidence >= 75 ? 'bg-green-500' : confidence >= 60 ? 'bg-yellow-500' : 'bg-ink-4'}`}
                        style={{ width: `${confidence}%` }}
                      />
                    </div>
                  </div>

                  {/* Resultado se tiver */}
                  {resultStyle && s.profit != null && (
                    <div className={`rounded-lg p-4 border flex items-center justify-between ${resultStyle.bg} ${resultStyle.border}`}>
                      <div>
                        <div className="text-xs text-ink-3 mb-0.5">Resultado</div>
                        <div className={`text-xl font-black ${resultStyle.text}`}>{resultStyle.label}</div>
                      </div>
                      <div className={`text-2xl font-black ${s.profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {fmtUnits(Number(s.profit), 2)}
                      </div>
                    </div>
                  )}

                  {/* Acoes ANTES da analise. O texto da IA e o bloco mais alto
                      do painel e empurrava os dois botoes pra fora da primeira
                      tela · quem abre pra compartilhar um green tinha que
                      rolar um paragrafo inteiro pra achar o botao. Decisao
                      primeiro, leitura depois. */}
                  {(
                  <div className="flex flex-wrap gap-2">
                    <button
                      onClick={() => setShowAnalysis(true)}
                      className="flex-1 min-w-[9rem] flex items-center justify-center gap-1.5 text-xs font-bold text-ink-2 border border-line-strong rounded-md py-2.5 hover:text-ink-1 hover:border-ink-4 transition-colors"
                    >
                      <Sparkles className="w-3.5 h-3.5" /> Entenda esta analise
                  </button>
                    <button
                      onClick={() => shareStory({
                        pickId: id,
                        pickTypeRoute: pickType === 'free' ? 'free' : pickType,
                        homeTeamName: s.home_team_name ?? s.home_team ?? 'Pick',
                        awayTeamName: s.away_team_name ?? s.away_team,
                        homeTeamId: s.home_team_id,
                        awayTeamId: s.away_team_id,
                        leagueName: s.league_name,
                        pickType: pickType === 'free' ? 'Dica do Dia' : (PICK_TYPE_LABEL[pickType] ?? 'VIP'),
                        market: translateMarket(s.market),
                        /* Mesma imagem do card: no pick de jogador a linha vai
                           sem o nome, que aparece embaixo da foto. */
                        line: s.player_name
                          ? linhaDoJogador(s.line, s.line_value, s.player_name)
                          : translateLine(s.line),
                        playerId: s.player_id ?? undefined,
                        playerName: s.player_name ?? undefined,
                        playerTeamName: s.team_name ?? undefined,
                        odd: Number(s.total_odd ?? s.odd ?? 0),
                        probabilityPct: pctProb(s.probability ?? s.confidence),
                        result: s.result,
                        profit: s.profit,
                      })}
                      disabled={sharing}
                      className="flex-1 min-w-[9rem] flex items-center justify-center gap-1.5 text-xs font-bold text-ink-2 border border-line-strong rounded-md py-2.5 hover:text-ink-1 hover:border-ink-4 transition-colors disabled:opacity-40"
                    >
                      <Share2 className="w-3.5 h-3.5" />
                      {sharing ? 'Gerando...' : shared ? 'Compartilhado' : 'Compartilhar'}
                  </button>
                  </div>
                  )}
                  {/* Raciocínio da IA */}
                  <div>
                    <p className="text-[10px] text-ink-3 mb-2">Análise da IA</p>
                    <div className="bg-surface-1 rounded-lg p-4 border border-line">
                      <p className="text-sm text-ink-2 leading-relaxed whitespace-pre-wrap">
                        {s.reasoning || 'Sem análise registrada.'}
                      </p>
                    </div>
                  </div>

                  {/* Múltipla / Alavancagem · legs */}
                  {(pickType === 'multipla' || pickType === 'alavancagem') && s.legs?.length > 0 && (
                    <div>
                      <p className="text-[10px] text-ink-3 mb-2">Jogos</p>
                      <div className="space-y-2">
                        {s.legs.map((g: any, i: number) => {
                          const homeTeam = g.home_team || g.home || ''
                          const awayTeam = g.away_team || g.away || ''
                          const homeLogo = g.home_team_id ? `/api/proxy/team/${g.home_team_id}.png` : null
                          const awayLogo = g.away_team_id ? `/api/proxy/team/${g.away_team_id}.png` : null
                          return (
                            <div key={i} className="bg-surface-1 border border-line rounded-lg px-4 py-3">
                              <div className="flex items-center justify-between gap-2">
                                <div className="flex items-center gap-1.5 flex-1 min-w-0 flex-wrap">
                                  {homeLogo && (
                                    <img src={homeLogo} alt="" width={16} height={16} className="w-4 h-4 object-contain shrink-0"
                                      onError={e => (e.currentTarget.style.display = 'none')} />
                                  )}
                                  <span className="text-sm font-semibold text-ink-1 truncate">{homeTeam}</span>
                                  <span className="text-ink-4 text-xs shrink-0">vs</span>
                                  {awayLogo && (
                                    <img src={awayLogo} alt="" width={16} height={16} className="w-4 h-4 object-contain shrink-0"
                                      onError={e => (e.currentTarget.style.display = 'none')} />
                                  )}
                                  <span className="text-sm font-semibold text-ink-1 truncate">{awayTeam}</span>
                                </div>
                                <span className="text-green-400 font-black shrink-0">{g.odd ? Number(g.odd).toFixed(2) : ''}</span>
                              </div>
                              <div className="text-xs text-ink-3 mt-0.5">{translateMarket(g.market)}{g.line ? `, ${translateLine(g.line)}` : ''}</div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}

                </div>
              )}

              {/* Chat em recolhido, no fim. Era uma aba; sem ela e sem isto
                  o recurso sumiria do site inteiro, porque este painel e o
                  UNICO lugar que renderiza PickSocial. */}
              <details className="mt-4 pt-4 border-t border-line">
                <summary className="cursor-pointer text-xs font-bold text-ink-3 hover:text-ink-1 select-none flex items-center gap-1.5">
                  <MessageCircle className="w-3.5 h-3.5" /> Comentários
                </summary>
                <div className="mt-3">
                  <PickSocial pickId={id} pickType={pickType} />
                </div>
              </details>

            </>
          )}
        </div>
      </motion.div>

    </motion.div>

    {/* Fora do painel, no body. Dentro dele o modal ficava preso no stacking
        context do z-[60] e abria ATRAS, visivel apagado no fundo -- era o bug
        que o usuario viu. O portal tambem impede que o clique nele borbulhe
        pro onClose do painel. */}
    {createPortal(
      <AnimatePresence>
        {showAnalysis && s && (
          <AnalysisModal
            onClose={() => setShowAnalysis(false)}
            data={{
              market: translateMarket(s.market),
              line: translateLine(s.line),
              marketRaw: s.market,
              lineRaw: s.line,
              /* Mesmo contexto que o card passa: sem ele o modal aberto pelo
                 painel caía no texto genérico de mercado desconhecido, e o
                 aberto pelo card escrevia a regra. */
              playerId: s.player_id ?? undefined,
              playerName: s.player_name ?? undefined,
              playerTeam: s.team_name ?? undefined,
              lineValue: s.line_value ?? undefined,
              pickId: id,
              pickType,
              odd: Number(s.total_odd ?? s.odd ?? 0),
              confidence: s.confidence,
              probability: s.probability,
              ev: s.ev,
              reasoning: s.reasoning,
              homeTeam: s.home_team_name ?? s.home_team,
              awayTeam: s.away_team_name ?? s.away_team,
            }}
          />
        )}
      </AnimatePresence>,
      document.body,
    )}
    </>
  )
}
