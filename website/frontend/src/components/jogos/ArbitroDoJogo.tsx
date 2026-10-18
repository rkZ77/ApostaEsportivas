import { useEffect, useMemo, useState } from 'react'
import api from '../../services/api'
import { cn } from '../../lib/cn'
import { Skeleton } from '../ui'
import { TeamLogo } from '../TeamLogo'

/*
 * O ÁRBITRO DA PARTIDA (16/10/2026, pedido do usuário: "quem é o árbitro,
 * quantos jogos apitou na temporada, média de faltas, cartões, VAR, e filtrar
 * só os jogos que ele apitou do time da casa e do outro time").
 *
 * Vive no fim da aba Estatísticas (e no começo, antes do jogo começar). Tudo
 * do banco (backend/arbitro_do_jogo.py): nenhuma chamada a API. VAR e pênalti
 * vêm dos eventos coletados, e a média diz em quantos jogos.
 */

interface Media { media: number; jogos: number }
interface Resumo {
  jogos: number
  faltas: Media | null; amarelos: Media | null; vermelhos: Media | null; pontos_de_cartao: Media | null
  amarelos_mandante: Media | null; amarelos_visitante: Media | null
  pct_mais_de_3_5_amarelos: number | null; pct_mais_de_4_5_amarelos: number | null
  penaltis: Media | null; var: Media | null
  pct_mandante_vence: number | null; pct_empate: number | null; pct_visitante_vence: number | null
}
interface Lance { minuto: number | null; team_id: number | null; lance: string }
interface Jogo {
  fixture_id: number; data: string; league_id: number
  home_team_id: number; away_team_id: number; home_team: string | null; away_team: string | null
  home_goals: number | null; away_goals: number | null
  amarelos: number | null; vermelhos: number | null; faltas: number | null
  home_amarelos: number | null; away_amarelos: number | null
  penaltis: number | null; var: Lance[] | null
}
interface Bloco { resumo: Resumo; jogos: Jogo[]; team_id?: number }
interface Resposta {
  status: 'ok' | 'sem_arbitro' | 'sem_jogo' | 'falhou'
  nome?: string; temporada?: number
  temporada_toda?: Bloco; nesta_liga?: Bloco; com_mandante?: Bloco; com_visitante?: Bloco
}
type Recorte = 'temporada_toda' | 'nesta_liga' | 'com_mandante' | 'com_visitante'

const num = (m: Media | null, casas = 1) =>
  m ? m.media.toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas }) : '-'
const dm = (iso: string) => { const [a, m, d] = iso.split('-'); return a ? `${d}/${m}/${a.slice(2)}` : '' }

export default function ArbitroDoJogo({ fixtureId, homeId, awayId, homeNome, awayNome }: {
  fixtureId: number; homeId?: number; awayId?: number; homeNome?: string; awayNome?: string
}) {
  const [r, setR] = useState<Resposta | null>(null)
  const [recorte, setRecorte] = useState<Recorte>('temporada_toda')
  const [mostrar, setMostrar] = useState(8)

  useEffect(() => {
    let vivo = true
    setR(null)
    api.get(`/fixtures/${fixtureId}/arbitro`)
      .then(res => { if (vivo) setR(res.data) })
      .catch(() => { if (vivo) setR({ status: 'falhou' }) })
    return () => { vivo = false }
  }, [fixtureId])
  useEffect(() => { setMostrar(8) }, [recorte])

  const bloco = r?.[recorte]
  // Com um time: a campanha DELE nos jogos apitados por este árbitro.
  const timeDoRecorte = recorte === 'com_mandante' ? homeId : recorte === 'com_visitante' ? awayId : undefined
  const campanha = useMemo(() => {
    if (!bloco || !timeDoRecorte) return null
    let v = 0, e = 0, d = 0, am = 0, n = 0
    for (const j of bloco.jogos) {
      if (j.home_goals == null || j.away_goals == null) continue
      const casa = j.home_team_id === timeDoRecorte
      const pro = casa ? j.home_goals : j.away_goals, contra = casa ? j.away_goals : j.home_goals
      if (pro > contra) v++; else if (pro === contra) e++; else d++
      const a = casa ? j.home_amarelos : j.away_amarelos
      if (a != null) { am += a; n++ }
    }
    return { v, e, d, amarelos: n ? am / n : null }
  }, [bloco, timeDoRecorte])

  if (!r) return <section id="arbitro-do-jogo" className="card p-4 scroll-mt-28"><Skeleton className="h-5 w-40 mb-3" /><Skeleton className="h-28 w-full" /></section>
  if (r.status !== 'ok' || !bloco) {
    return (
      <section id="arbitro-do-jogo" className="card p-4 scroll-mt-28">
        <h3 className="text-[11px] font-bold uppercase tracking-wide text-ink-3">Árbitro</h3>
        <p className="mt-1.5 text-sm text-ink-3">
          {r.status === 'sem_arbitro' ? 'A escala de arbitragem ainda não saiu. Ela costuma sair 1 ou 2 dias antes do jogo.'
            : 'Não deu pra carregar os números do árbitro agora.'}
        </p>
      </section>
    )
  }

  const s = bloco.resumo
  const emJogos = (m: Media | null) => m && m.jogos < s.jogos ? `em ${m.jogos} ${m.jogos === 1 ? 'jogo' : 'jogos'}` : undefined
  // Escudo + Casa/Fora: o nome do time não cabe em 1/4 da tela do celular
  // ("1. FC Nürnberg" virava "1. FC").
  const recortes: [Recorte, React.ReactNode, string][] = [
    ['temporada_toda', 'Temporada', 'Temporada inteira'], ['nesta_liga', 'Esta liga', 'Só esta liga'],
    ['com_mandante', <><TeamLogo id={homeId} name="" size={16} />Casa</>, `Jogos dele com ${homeNome ?? 'o mandante'}`],
    ['com_visitante', <><TeamLogo id={awayId} name="" size={16} />Fora</>, `Jogos dele com ${awayNome ?? 'o visitante'}`],
  ]
  const celulas: [string, string, string?][] = [
    ['Jogos apitados', String(s.jogos)],
    ['Faltas por jogo', num(s.faltas)],
    ['Amarelos por jogo', num(s.amarelos)],
    ['Vermelhos por jogo', num(s.vermelhos, 2)],
    ['Pontos de cartão', num(s.pontos_de_cartao), 'amarelo + 2 x vermelho'],
    ['Mais de 4,5 amarelos', s.pct_mais_de_4_5_amarelos == null ? '-' : `${s.pct_mais_de_4_5_amarelos}%`, 'dos jogos'],
    ['Pênaltis por jogo', num(s.penaltis, 2), emJogos(s.penaltis)],
    ['VAR por jogo', num(s.var, 2), emJogos(s.var)],
  ]

  return (
    <section id="arbitro-do-jogo" className="card overflow-hidden scroll-mt-28">
      <div className="px-4 pt-4 pb-3">
        <div className="text-[11px] font-bold uppercase tracking-wide text-ink-3">Árbitro da partida</div>
        <div className="mt-0.5 text-lg font-bold text-ink-1">{r.nome}</div>
        <div className="text-[11px] text-ink-3">Temporada {r.temporada}, em todas as competições que ele apitou</div>
      </div>

      {/* Os quatro recortes à vista, como as abas: o dedo acerta (40px). */}
      <div className="px-4 pb-3">
        <div className="grid grid-cols-4 rounded-lg border border-line p-0.5 bg-surface-1">
          {recortes.map(([k, rotulo, nomeCompleto]) => (
            <button key={k} type="button" aria-pressed={recorte === k} onClick={() => setRecorte(k)}
              aria-label={nomeCompleto} title={nomeCompleto}
              className={cn('h-10 px-1 rounded-md text-xs font-bold flex items-center justify-center gap-1 transition-colors',
                recorte === k ? 'bg-surface-3 text-ink-1' : 'text-ink-3')}>
              {rotulo}
            </button>
          ))}
        </div>
      </div>

      {s.jogos === 0 ? (
        <p className="px-4 pb-4 text-sm text-ink-3">
          {timeDoRecorte ? 'Ele ainda não apitou nenhum jogo deste time na nossa base.' : 'Sem jogos dele neste recorte ainda.'}
        </p>
      ) : (
        <>
          {campanha && (
            <div className="mx-4 mb-3 flex items-center gap-3 rounded-lg bg-surface-2/60 px-3 py-2.5">
              <TeamLogo id={timeDoRecorte} name="" size={22} />
              <div className="text-sm text-ink-2">
                Com ele: <b className="text-ink-1">{campanha.v}V {campanha.e}E {campanha.d}D</b>
                {campanha.amarelos != null && <>, {campanha.amarelos.toLocaleString('pt-BR', { maximumFractionDigits: 1 })} amarelos do time por jogo</>}
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 min-[480px]:grid-cols-4 gap-px bg-line/60 border-y border-line/60">
            {celulas.map(([rotulo, valor, nota]) => (
              <div key={rotulo} className="bg-surface-1 px-3 py-3">
                <div className="text-[11px] text-ink-3 leading-tight">{rotulo}</div>
                <div className="font-mono font-black text-2xl leading-none text-ink-1 mt-1.5">{valor}</div>
                {nota && <div className="mt-1 text-[11px] text-ink-4">{nota}</div>}
              </div>
            ))}
          </div>

          <div className="px-4 py-3 space-y-1.5 text-sm text-ink-2">
            {s.pct_mandante_vence != null && (
              <p>
                <span className="text-[11px] font-bold uppercase tracking-wide text-ink-3 mr-1.5">Resultado</span>
                mandante vence {s.pct_mandante_vence}%, empate {s.pct_empate}%, visitante {s.pct_visitante_vence}%
              </p>
            )}
            {s.amarelos_mandante && s.amarelos_visitante && (
              <p>
                <span className="text-[11px] font-bold uppercase tracking-wide text-ink-3 mr-1.5">Amarelos</span>
                {num(s.amarelos_mandante)} pro mandante, {num(s.amarelos_visitante)} pro visitante
              </p>
            )}
          </div>

          <ul className="divide-y divide-line/60 border-t border-line/60">
            {bloco.jogos.slice(0, mostrar).map(j => (
              <li key={j.fixture_id} className="px-4 py-2.5">
                <div className="flex items-center gap-2">
                  <span className="w-[62px] shrink-0 font-mono text-[11px] text-ink-4">{dm(j.data)}</span>
                  <span className="flex-1 min-w-0 text-[13px] text-ink-1 truncate">
                    {j.home_team ?? 'Casa'} <b className="font-mono">{j.home_goals ?? '-'}-{j.away_goals ?? '-'}</b> {j.away_team ?? 'Fora'}
                  </span>
                </div>
                <div className="mt-1 pl-[70px] flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink-3">
                  <span>{j.amarelos ?? '-'} amarelos</span>
                  {!!j.vermelhos && <span>{j.vermelhos} vermelho{j.vermelhos > 1 ? 's' : ''}</span>}
                  <span>{j.faltas ?? '-'} faltas</span>
                  {!!j.penaltis && <span>{j.penaltis} pênalti{j.penaltis > 1 ? 's' : ''}</span>}
                  {(j.var ?? []).map((v, i) => (
                    <span key={i} className="px-1.5 rounded border border-line-strong text-ink-2">
                      VAR {v.minuto != null ? `${v.minuto}' ` : ''}{v.lance}
                    </span>
                  ))}
                </div>
              </li>
            ))}
          </ul>
          {bloco.jogos.length > mostrar && (
            <button type="button" onClick={() => setMostrar(m => m + 10)}
              className="w-full h-11 border-t border-line/60 text-sm font-semibold text-ink-2 hover:text-ink-1">
              Ver mais jogos
            </button>
          )}
          <p className="px-4 py-2.5 border-t border-line/60 text-[11px] text-ink-4 leading-relaxed">
            VAR e pênalti só contam os jogos com os eventos coletados. Casa e Fora olham todas as temporadas,
            porque o encontro de árbitro com time é raro.
          </p>
        </>
      )}
    </section>
  )
}
