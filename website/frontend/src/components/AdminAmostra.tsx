import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import api from '../services/api'
import { Drawer, SpinnerBlock } from './ui'

/*
 * A amostra por trás da média.
 *
 * `team_statistics` e `referee_stats` guardam UM número por contexto, e é dele
 * que o motor decide. A pergunta de trás nunca teve tela: que jogos entraram
 * nessa média.
 *
 * Sem a lista, "média de 9,4 escanteios" é indistinguível em três casos que
 * pedem reações opostas:
 *
 *   18 jogos coletados inteiros             o número é o número
 *   3 jogos                                 é amostra, não tendência
 *   18 jogos, 7 sem escanteio na folha      é média puxada por buraco de coleta
 *
 * O terceiro é o que morde. O agregador soma `valor or 0` e conta o jogo do
 * mesmo jeito (services/match_stats_service_media.py::_aggregate_games): jogo
 * com o contador ausente entra na média COMO ZERO. Folha furada não some da
 * média, ela a distorce · por isso a linha do jogo com buraco é marcada aqui.
 *
 * A média mostrada não é recalculada pela tela. Vem do mesmo método que o
 * pipeline chama · tela feita pra conferir o motor não pode ter a própria
 * aritmética.
 */

export type AlvoAmostra =
  | { tipo: 'time'; teamId: number; leagueId?: number | null; season?: number | null; nome?: string | null }
  | { tipo: 'arbitro'; refereeId: number; season?: number | null; nome?: string | null }

interface JogoTime {
  fixture_id: number
  data: string | null
  em_casa: boolean
  adversario: string | null
  gols_pro: number | null
  gols_contra: number | null
  stats: Record<string, [number | null, number | null]>
  buracos: string[]
}

interface JogoArbitro {
  fixture_id: number
  data: string | null
  liga: string | null
  mandante: string | null
  visitante: string | null
  total_goals: number | null
  total_yellow_cards: number | null
  total_red_cards: number | null
  total_corners: number | null
  total_fouls: number | null
  buracos: string[]
}

const diaMes = (iso?: string | null) => {
  if (!iso) return '·'
  const [a, m, d] = iso.slice(0, 10).split('-')
  return d && m ? `${d}/${m}` : a
}

const dec = (v: unknown) => {
  const n = typeof v === 'string' ? Number(v) : v
  return typeof n === 'number' && !Number.isNaN(n)
    ? n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : '·'
}

const inteiro = (v: number | null | undefined) => (v == null ? '·' : String(v))

/** As médias que se lê olhando um jogo · o resto de team_statistics é ruído
 *  numa tela de conferência (28 colunas de avg_* não cabem em nada). */
const MEDIAS_DO_TIME: [string, string][] = [
  ['avg_goals_for', 'Gols pró'],
  ['avg_goals_against', 'Gols contra'],
  ['avg_total_goals', 'Gols no jogo'],
  ['avg_corners_for', 'Escanteios pró'],
  ['avg_total_corners', 'Escanteios no jogo'],
  ['avg_yellow_for', 'Amarelos do time'],
  ['avg_total_yellow', 'Amarelos no jogo'],
  ['avg_fouls_for', 'Faltas cometidas'],
  ['avg_total_shots_for', 'Chutes'],
  ['avg_shots_on_for', 'Chutes a gol'],
  ['avg_saves_for', 'Defesas'],
  ['avg_possession_for', 'Posse (%)'],
]

export default function AdminAmostra({ alvo, onClose }: { alvo: AlvoAmostra; onClose: () => void }) {
  const [dados, setDados] = useState<any>(null)
  const [carregando, setCarregando] = useState(true)
  const [erro, setErro] = useState('')
  const [season, setSeason] = useState<number | null>(alvo.season ?? null)

  useEffect(() => {
    setCarregando(true)
    setErro('')
    const url = alvo.tipo === 'time'
      ? `/admin/dados/times/${alvo.teamId}/amostra`
      : `/admin/dados/arbitros/${alvo.refereeId}/amostra`
    const params: Record<string, unknown> = {}
    if (season != null) params.season = season
    if (alvo.tipo === 'time' && alvo.leagueId != null) params.league_id = alvo.leagueId
    api.get(url, { params })
      .then(r => {
        setDados(r.data)
        if (season == null && r.data?.season != null) setSeason(r.data.season)
      })
      .catch(e => setErro(e?.response?.data?.detail ?? 'Não deu pra ler a amostra.'))
      .finally(() => setCarregando(false))
    // `season` fecha o ciclo de troca de temporada; o alvo não muda com o drawer aberto.
  }, [alvo, season])

  const titulo = alvo.tipo === 'time'
    ? (dados?.time?.nome ?? alvo.nome ?? 'Time')
    : (dados?.arbitro?.nome ?? alvo.nome ?? 'Árbitro')

  return (
    <Drawer
      onClose={onClose}
      title={titulo}
      description={alvo.tipo === 'time'
        ? 'Os jogos que entraram na média deste time, e a média que saiu deles.'
        : 'Os jogos que entraram na média deste árbitro, e a média que saiu deles.'}
    >
      {carregando ? (
        <SpinnerBlock className="py-20" />
      ) : erro ? (
        <p className="text-red-400 text-sm py-6">{erro}</p>
      ) : !dados ? null : (
        <div className="space-y-5">
          {/* Recorte. Time é por liga E temporada porque é assim que o motor lê:
            * o mesmo time tem uma média no Brasileirão e outra na Sul-Americana,
            * e misturar as duas é comparar competições diferentes. */}
          {alvo.tipo === 'time' && !!dados.contextos?.length && (
            <select
              value={`${dados.league_id}|${dados.season}`}
              onChange={e => {
                const [lid, sea] = e.target.value.split('|')
                setDados(null)
                setCarregando(true)
                api.get(`/admin/dados/times/${(alvo as any).teamId}/amostra`,
                        { params: { league_id: Number(lid), season: Number(sea) } })
                  .then(r => setDados(r.data))
                  .catch(() => setErro('Não deu pra ler a amostra.'))
                  .finally(() => setCarregando(false))
              }}
              className="w-full bg-surface-1 border border-line-strong rounded-md text-xs text-ink-2 px-2 py-2 min-h-[40px] focus:border-ink-4 focus:outline-none"
              aria-label="Competição e temporada"
            >
              {dados.contextos.map((c: any) => (
                <option key={`${c.league_id}|${c.season}`} value={`${c.league_id}|${c.season}`}>
                  {c.liga ?? `liga ${c.league_id}`} · {c.season} · {c.jogos} jogo(s)
                </option>
              ))}
            </select>
          )}

          {alvo.tipo === 'arbitro' && dados.temporadas?.length > 1 && (
            <select
              value={dados.season ?? ''}
              onChange={e => setSeason(Number(e.target.value))}
              className="w-full bg-surface-1 border border-line-strong rounded-md text-xs text-ink-2 px-2 py-2 min-h-[40px] focus:border-ink-4 focus:outline-none"
              aria-label="Temporada"
            >
              {dados.temporadas.map((s: number) => <option key={s} value={s}>{s}</option>)}
            </select>
          )}

          {/* O aviso vem antes dos números de propósito: ele muda como se lê
            * todo o resto da tela. */}
          {dados.jogos_com_buraco > 0 && (
            <div className="flex items-start gap-2.5 rounded-lg border border-yellow-500/40 bg-yellow-500/5 p-3">
              <AlertTriangle className="w-4 h-4 text-yellow-400 shrink-0 mt-0.5" />
              <p className="text-[11px] text-ink-3 leading-relaxed">
                <span className="font-bold text-ink-1">
                  {dados.jogos_com_buraco} de {dados.jogos.length} jogo(s) entraram com estatística faltando.
                </span>{' '}
                O agregador soma o contador ausente como zero e conta o jogo do mesmo jeito ·
                então a média não fica só menos confiável, ela fica menor. É o mesmo buraco que
                a lista de partidas mostra em amarelo, visto do lado da média.
              </p>
            </div>
          )}

          {/* Médias. Do time vêm em dois contextos (casa e fora), porque é
            * assim que elas são gravadas · não existe "geral". */}
          {alvo.tipo === 'time' ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {['HOME', 'AWAY'].map(ctx => {
                const motor = dados.media_do_motor?.[ctx]
                const salva = dados.media_salva?.[ctx]
                if (!motor && !salva) return null
                return (
                  <div key={ctx} className="rounded-lg border border-line p-3">
                    <div className="flex items-baseline justify-between gap-2 mb-2">
                      <p className="text-xs font-bold text-ink-1">
                        {ctx === 'HOME' ? 'Em casa' : 'Fora'}
                      </p>
                      <p className="text-[10px] font-mono text-ink-4">
                        {motor?.games_count ?? salva?.games_count ?? '·'} jogo(s)
                      </p>
                    </div>
                    <div className="space-y-1">
                      {MEDIAS_DO_TIME.map(([chave, rotulo]) => {
                        const a = motor?.[chave]
                        const b = salva?.[chave]
                        // Gravado diferente do que o motor calcula AGORA = média
                        // velha. `match_statistics` em dia com `team_statistics`
                        // parada não tem sintoma nenhum na tela do site.
                        const difere = a != null && b != null && Number(a).toFixed(2) !== Number(b).toFixed(2)
                        return (
                          <div key={chave} className="flex items-baseline justify-between gap-2 text-[11px]">
                            <span className="text-ink-3 truncate">{rotulo}</span>
                            <span className={`font-mono tabular-nums shrink-0 ${
                              difere ? 'text-yellow-400' : 'text-ink-1'}`}>
                              {dec(a ?? b)}
                              {difere && <span className="text-ink-4 ml-1.5">salvo {dec(b)}</span>}
                            </span>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )
              })}
            </div>
          ) : dados.media_salva ? (
            <div className="rounded-lg border border-line p-3">
              <div className="flex items-baseline justify-between gap-2 mb-2">
                <p className="text-xs font-bold text-ink-1">Média gravada</p>
                <p className="text-[10px] font-mono text-ink-4">
                  {dados.media_salva.games ?? '·'} com folha
                  {dados.media_salva.games_total != null &&
                    ` · ${dados.media_salva.games_total} apitados`}
                </p>
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                {[['avg_yellow', 'Amarelos'], ['avg_red', 'Vermelhos'], ['avg_fouls', 'Faltas'],
                  ['avg_corners', 'Escanteios'], ['avg_goals', 'Gols'],
                  ['max_yellow', 'Máx. amarelos']].map(([chave, rotulo]) => (
                  <div key={chave} className="flex items-baseline justify-between gap-2 text-[11px]">
                    <span className="text-ink-3 truncate">{rotulo}</span>
                    <span className="font-mono tabular-nums text-ink-1 shrink-0">
                      {dec(dados.media_salva[chave])}
                    </span>
                  </div>
                ))}
              </div>
              <p className="text-[10px] text-ink-4 mt-2 leading-relaxed">
                "Com folha" é a amostra que sustenta a média de cartões · é esse número que o
                gate do motor lê. A distância dele para os apitados é quanta coleta falta.
              </p>
            </div>
          ) : (
            <p className="text-[11px] text-yellow-400">
              Nenhuma média gravada para esta temporada. Recalcule na aba Dados.
            </p>
          )}

          {/* Os jogos. */}
          <div>
            <p className="text-xs font-bold text-ink-1 mb-2">
              {dados.jogos.length} jogo(s) na amostra
            </p>
            <div className="rounded-lg border border-line/60 divide-y divide-line/60 overflow-hidden">
              {dados.jogos.map((j: JogoTime | JogoArbitro) => {
                const comBuraco = j.buracos.length > 0
                return (
                  <div key={j.fixture_id} className={`px-3 py-2 ${comBuraco ? 'bg-yellow-500/5' : ''}`}>
                    {alvo.tipo === 'time' ? (
                      <>
                        <div className="flex items-baseline gap-2">
                          <span className="font-mono text-[10px] text-ink-4 w-9 shrink-0 tabular-nums">
                            {diaMes(j.data)}
                          </span>
                          <span className="flex-1 min-w-0 text-[12px] text-ink-2 truncate">
                            {(j as JogoTime).em_casa ? 'x ' : '@ '}
                            {(j as JogoTime).adversario ?? 'Time ?'}
                          </span>
                          <span className="font-mono text-[11px] text-ink-1 tabular-nums shrink-0">
                            {inteiro((j as JogoTime).gols_pro)}-{inteiro((j as JogoTime).gols_contra)}
                          </span>
                        </div>
                        <div className="flex flex-wrap gap-x-3 pl-11 mt-0.5 text-[10px] font-mono text-ink-4 tabular-nums">
                          <span>esc {inteiro((j as JogoTime).stats?.escanteios?.[0])}</span>
                          <span>chu {inteiro((j as JogoTime).stats?.chutes?.[0])}</span>
                          <span>fal {inteiro((j as JogoTime).stats?.faltas?.[0])}</span>
                          <span>ama {inteiro((j as JogoTime).stats?.amarelos?.[0])}</span>
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="flex items-baseline gap-2">
                          <span className="font-mono text-[10px] text-ink-4 w-9 shrink-0 tabular-nums">
                            {diaMes(j.data)}
                          </span>
                          <span className="flex-1 min-w-0 text-[12px] text-ink-2 truncate">
                            {(j as JogoArbitro).mandante ?? 'Time ?'} x {(j as JogoArbitro).visitante ?? 'Time ?'}
                          </span>
                        </div>
                        <div className="flex flex-wrap gap-x-3 pl-11 mt-0.5 text-[10px] font-mono text-ink-4 tabular-nums">
                          <span>ama {inteiro((j as JogoArbitro).total_yellow_cards)}</span>
                          <span>ver {inteiro((j as JogoArbitro).total_red_cards)}</span>
                          <span>fal {inteiro((j as JogoArbitro).total_fouls)}</span>
                          <span>esc {inteiro((j as JogoArbitro).total_corners)}</span>
                          <span className="truncate max-w-[8rem]">{(j as JogoArbitro).liga ?? ''}</span>
                        </div>
                      </>
                    )}
                    {comBuraco && (
                      <p className="pl-11 mt-0.5 text-[10px] text-yellow-400">
                        entrou como zero em: {j.buracos.join(', ')}
                      </p>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}
    </Drawer>
  )
}
