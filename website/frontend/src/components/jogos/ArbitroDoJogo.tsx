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
  liga_nome?: string | null; extra?: boolean
  home_team_id: number; away_team_id: number; home_team: string | null; away_team: string | null
  home_goals: number | null; away_goals: number | null
  amarelos: number | null; vermelhos: number | null; faltas: number | null
  home_amarelos: number | null; away_amarelos: number | null
  penaltis: number | null; var: Lance[] | null
}
interface Bloco { resumo: Resumo; jogos: Jogo[]; team_id?: number }
interface Resposta {
  status: 'ok' | 'sem_arbitro' | 'sem_jogo' | 'falhou'
  nome?: string; temporada?: number; de_outras_competicoes?: number
  contexto?: Contexto
  temporada_toda?: Bloco; nesta_liga?: Bloco; com_mandante?: Bloco; com_visitante?: Bloco
}
type Recorte = 'temporada_toda' | 'nesta_liga' | 'com_mandante' | 'com_visitante'
/** O árbitro contra a liga e o cartão do confronto (18/10/2026, backend/arbitro_do_jogo.contexto). */
interface Contexto {
  perfil?: 'rigoroso' | 'leniente' | 'na_media_da_liga' | 'amostra_curta'
  pontos_de_cartao?: number; pontos_de_cartao_da_liga?: number
  faltas?: number; faltas_da_liga?: number
  perfil_de_faltas?: 'marca_muita_falta' | 'deixa_o_jogo_correr' | 'faltas_na_media_da_liga'
  confronto?: { confrontos: number; media_h2h: number; baseline: number; label: string }
  temperatura?: string
}
const PERFIL: Record<string, string> = { rigoroso: 'Rigoroso', leniente: 'Leniente', na_media_da_liga: 'Na média da liga' }
const PERFIL_FALTAS: Record<string, string> = { marca_muita_falta: 'Marca muita falta', deixa_o_jogo_correr: 'Deixa o jogo correr' }
const TEMPERATURA: Record<string, string> = {
  confronto_quente_com_arbitro_rigoroso: 'Confronto quente com árbitro rigoroso: tende a ter cartão acima do normal.',
  confronto_quente_com_arbitro_leniente: 'Confronto quente, mas o árbitro costuma segurar os cartões.',
  confronto_frio_com_arbitro_rigoroso: 'Confronto frio, mas o árbitro é rigoroso.',
  confronto_frio_com_arbitro_leniente: 'Confronto frio e árbitro leniente: tende a ter menos cartão.',
}
const dec = (n: number) => n.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
interface MediaDaLiga { amarelos: number; vermelhos: number; faltas: number; jogos: number }

/** Linha que o gráfico de amarelos marca: a mesma do tile "Mais de 4,5". */
const LINHA_AMARELOS = 4.5

/* O que a API ainda manda em inglês e o mapa do backend não pega
   ("Card upgrade confirmed" aparecia cru na lista). */
const VAR_RESTO: [RegExp, string][] = [
  [/card (upgrade|reviewed|downgrade)/i, 'Cartão revisto'],
  [/goal (cancel+ed|disallowed)/i, 'Gol anulado'], [/goal confirmed/i, 'Gol confirmado'],
  [/penalty (cancel+ed|not awarded)/i, 'Pênalti cancelado'], [/penalty (confirmed|awarded)/i, 'Pênalti confirmado'],
]
const lanceVar = (t: string) => VAR_RESTO.find(([re]) => re.test(t))?.[1] ?? t

/* Perfil pela pontuação de cartão (amarelo + 2 x vermelho) contra a da liga.
   15% pra cada lado é o corte: menos que isso é ruído de amostra. Rigoroso
   não é vermelho: vermelho no site é só RED de pick. */
function perfilDoArbitro(dele: number, daLiga: number) {
  const dif = daLiga > 0 ? dele / daLiga - 1 : 0
  if (dif >= 0.15) return { rotulo: 'Rigoroso', dif, cls: 'bg-amber-400/15 text-amber-300 border-amber-400/40' }
  if (dif <= -0.15) return { rotulo: 'Deixa jogar', dif, cls: 'bg-sky-400/15 text-sky-300 border-sky-400/40' }
  return { rotulo: 'Na média', dif, cls: 'bg-surface-3 text-ink-2 border-line-strong' }
}

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

  /* A MÉDIA DA LIGA, PRA DIZER SE ELE É RIGOROSO (18/10/2026, pedido do
     usuário: "melhora o formato do árbitro, deixa mais inovador"). Vem do
     mesmo /liga/tendencias da aba Ligas: banco, sem API. A liga sai dos jogos
     dele nesta liga; sem jogo dele aqui, o perfil não aparece. */
  const ligaId = r?.nesta_liga?.jogos[0]?.league_id
  const [liga, setLiga] = useState<MediaDaLiga | null>(null)
  useEffect(() => {
    setLiga(null)
    if (!ligaId) return
    let vivo = true
    api.get('/suggestions/liga/tendencias', { params: { league_id: ligaId, limit: 500 } })
      .then(res => {
        const m = res.data?.summary
        if (vivo && m?.total_games >= 10) setLiga({
          amarelos: m.avg_yellow_cards, vermelhos: m.avg_red_cards, faltas: m.avg_fouls, jogos: m.total_games,
        })
      })
      .catch(() => { /* sem assinatura ou sem dado: o resto da tela segue */ })
    return () => { vivo = false }
  }, [ligaId])

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

  // O perfil só faz sentido nos recortes de temporada; com um time a amostra é outra.
  const pontosDaLiga = liga ? liga.amarelos + 2 * liga.vermelhos : 0
  const perfil = liga && !timeDoRecorte && s.pontos_de_cartao && s.jogos >= 3
    ? perfilDoArbitro(s.pontos_de_cartao.media, pontosDaLiga) : null
  const comparacao = !liga ? [] : [
    { rotulo: 'Amarelos', dele: s.amarelos?.media, daLiga: liga.amarelos },
    { rotulo: 'Faltas', dele: s.faltas?.media, daLiga: liga.faltas },
    { rotulo: 'Pontos de cartão', dele: s.pontos_de_cartao?.media, daLiga: pontosDaLiga },
  ].filter((c): c is { rotulo: string; dele: number; daLiga: number } => c.dele != null && c.daLiga > 0)
  // Do mais antigo pro mais novo, como se lê um gráfico de tempo.
  const serie = bloco.jogos.filter(j => j.amarelos != null).slice(0, 12).reverse()

  return (
    <section id="arbitro-do-jogo" className="card overflow-hidden scroll-mt-28">
      <div className="px-4 pt-4 pb-3">
        <div className="text-[11px] font-bold uppercase tracking-wide text-ink-3">Árbitro da partida</div>
        <div className="mt-0.5 text-lg font-bold text-ink-1">{r.nome}</div>
        <div className="text-[11px] text-ink-3">
          Temporada {r.temporada}, em todas as competições que ele apitou
          {!!r.de_outras_competicoes && <>, com {r.de_outras_competicoes} {r.de_outras_competicoes === 1 ? 'jogo' : 'jogos'} de outras competições do país</>}
        </div>
        {r.contexto && (PERFIL[r.contexto.perfil ?? ''] || PERFIL_FALTAS[r.contexto.perfil_de_faltas ?? ''] || r.contexto.confronto) && (
          <div className="mt-2.5 space-y-1.5 text-[13px] text-ink-2">
            {PERFIL[r.contexto.perfil ?? ''] && r.contexto.pontos_de_cartao != null && r.contexto.pontos_de_cartao_da_liga != null && (
              <p>
                <span className="mr-1.5 px-1.5 py-0.5 rounded border border-line-strong text-[11px] font-bold text-ink-1">{PERFIL[r.contexto.perfil!]}</span>
                {dec(r.contexto.pontos_de_cartao)} pontos de cartão por jogo; a liga dá {dec(r.contexto.pontos_de_cartao_da_liga)}
              </p>
            )}
            {PERFIL_FALTAS[r.contexto.perfil_de_faltas ?? ''] && r.contexto.faltas != null && r.contexto.faltas_da_liga != null && (
              <p>
                <span className="mr-1.5 px-1.5 py-0.5 rounded border border-line-strong text-[11px] font-bold text-ink-1">{PERFIL_FALTAS[r.contexto.perfil_de_faltas!]}</span>
                {dec(r.contexto.faltas)} faltas por jogo; a liga tem {dec(r.contexto.faltas_da_liga)}
              </p>
            )}
            {r.contexto.confronto && (
              <p className="text-ink-3">
                Confronto direto: {dec(r.contexto.confronto.media_h2h)} pontos de cartão nos últimos {r.contexto.confronto.confrontos} jogos entre os dois; o esperado pelos times é {dec(r.contexto.confronto.baseline)}.
              </p>
            )}
            {TEMPERATURA[r.contexto.temperatura ?? ''] && <p className="font-semibold text-ink-1">{TEMPERATURA[r.contexto.temperatura!]}</p>}
          </div>
        )}
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

          {perfil && liga && (
            <div className="mx-4 mb-3 rounded-xl border border-line bg-surface-2/40 p-3">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={cn('h-7 px-2.5 rounded-full border text-xs font-black uppercase tracking-wide flex items-center', perfil.cls)}>
                  {perfil.rotulo}
                </span>
                <span className="text-sm text-ink-2">
                  {Math.abs(perfil.dif) < 0.005 ? 'Cartão igual à média da liga'
                    : <>{Math.round(Math.abs(perfil.dif) * 100)}% {perfil.dif > 0 ? 'mais' : 'menos'} cartão que a média da liga</>}
                </span>
              </div>
              <div className="mt-3 space-y-2.5">
                {comparacao.map(c => <BarraContraLiga key={c.rotulo} {...c} />)}
              </div>
              <div className="mt-2.5 flex items-center gap-3 text-[11px] text-ink-3">
                <span className="flex items-center gap-1.5"><span className="w-3 h-1.5 rounded-full bg-accent" />Ele</span>
                <span className="flex items-center gap-1.5"><span className="w-3 h-1.5 rounded-full bg-ink-4" />Média da liga ({liga.jogos} jogos)</span>
              </div>
            </div>
          )}

          {serie.length >= 3 && <AmarelosJogoAJogo jogos={serie} />}

          <div className="grid grid-cols-2 min-[480px]:grid-cols-4 gap-px bg-line/60 border-y border-line/60">
            {celulas.map(([rotulo, valor, nota]) => (
              <div key={rotulo} className="bg-surface-1 px-3 py-3">
                <div className="text-[11px] text-ink-3 leading-tight">{rotulo}</div>
                <div className="font-mono font-black text-2xl leading-none text-ink-1 mt-1.5">{valor}</div>
                {nota && <div className="mt-1 text-[11px] text-ink-4">{nota}</div>}
              </div>
            ))}
          </div>

          {(s.pct_mandante_vence != null || (s.amarelos_mandante && s.amarelos_visitante)) && (
            <div className="px-4 py-3 space-y-3">
              {s.pct_mandante_vence != null && (
                <BarraDividida titulo="Resultado com ele" partes={[
                  { rotulo: 'Mandante', valor: s.pct_mandante_vence, texto: `${s.pct_mandante_vence}%`, cls: 'bg-accent' },
                  { rotulo: 'Empate', valor: s.pct_empate ?? 0, texto: `${s.pct_empate ?? 0}%`, cls: 'bg-ink-4' },
                  { rotulo: 'Visitante', valor: s.pct_visitante_vence ?? 0, texto: `${s.pct_visitante_vence ?? 0}%`, cls: 'bg-sky-400' },
                ]} />
              )}
              {s.amarelos_mandante && s.amarelos_visitante && (
                <BarraDividida titulo="Pra quem vai o amarelo" partes={[
                  { rotulo: 'Mandante', valor: s.amarelos_mandante.media, texto: num(s.amarelos_mandante), cls: 'bg-accent' },
                  { rotulo: 'Visitante', valor: s.amarelos_visitante.media, texto: num(s.amarelos_visitante), cls: 'bg-sky-400' },
                ]} />
              )}
            </div>
          )}

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
                  {j.liga_nome && <span className="text-ink-2">{j.liga_nome}</span>}
                  <span>{j.amarelos ?? '-'} amarelos</span>
                  {!!j.vermelhos && <span>{j.vermelhos} vermelho{j.vermelhos > 1 ? 's' : ''}</span>}
                  <span>{j.faltas ?? '-'} faltas</span>
                  {!!j.penaltis && <span>{j.penaltis} pênalti{j.penaltis > 1 ? 's' : ''}</span>}
                  {(j.var ?? []).map((v, i) => (
                    <span key={i} className="px-1.5 rounded border border-line-strong text-ink-2">
                      VAR {v.minuto != null ? `${v.minuto}' ` : ''}{lanceVar(v.lance)}
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
            Pontos de cartão: amarelo vale 1 e vermelho vale 2. VAR e pênalti só contam os jogos com os eventos coletados. Casa e Fora olham todas as temporadas,
            porque o encontro de árbitro com time é raro.
          </p>
        </>
      )}
    </section>
  )
}

const umaCasa = (v: number) => v.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

/* Ele contra a liga num número: duas barras finas na mesma escala e o valor
   escrito ao lado, pra cor não carregar o dado sozinha. */
function BarraContraLiga({ rotulo, dele, daLiga }: { rotulo: string; dele: number; daLiga: number }) {
  const teto = Math.max(dele, daLiga) * 1.1
  return (
    <div title={`${rotulo}: ele ${umaCasa(dele)}, liga ${umaCasa(daLiga)}`}>
      <div className="flex items-baseline justify-between text-[11px]">
        <span className="text-ink-2 font-semibold">{rotulo} por jogo</span>
        <span className="font-mono text-ink-3"><b className="text-ink-1">{umaCasa(dele)}</b> x {umaCasa(daLiga)}</span>
      </div>
      <div className="mt-1 space-y-[2px]">
        <div className="h-1.5 rounded-full bg-surface-3/60">
          <div className="h-full rounded-full bg-accent" style={{ width: `${(dele / teto) * 100}%` }} />
        </div>
        <div className="h-1.5 rounded-full bg-surface-3/60">
          <div className="h-full rounded-full bg-ink-4" style={{ width: `${(daLiga / teto) * 100}%` }} />
        </div>
      </div>
    </div>
  )
}

/* Uma barra dividida em partes, com rótulo e valor de cada parte embaixo. */
function BarraDividida({ titulo, partes }: {
  titulo: string; partes: { rotulo: string; valor: number; texto: string; cls: string }[]
}) {
  const total = partes.reduce((t, p) => t + p.valor, 0) || 1
  return (
    <div>
      <div className="text-[11px] font-bold uppercase tracking-wide text-ink-3">{titulo}</div>
      <div className="mt-1.5 flex h-2.5 gap-[2px]" role="img" aria-label={partes.map(p => `${p.rotulo} ${p.texto}`).join(', ')}>
        {partes.filter(p => p.valor > 0).map(p => (
          <div key={p.rotulo} className={cn('h-full rounded-[4px]', p.cls)}
            style={{ width: `${(p.valor / total) * 100}%` }} title={`${p.rotulo}: ${p.texto}`} />
        ))}
      </div>
      <div className="mt-1.5 flex justify-between gap-2 text-[11px]">
        {partes.map(p => (
          <span key={p.rotulo} className="flex items-center gap-1.5 text-ink-3 min-w-0">
            <span className={cn('w-2 h-2 rounded-full shrink-0', p.cls)} />
            <span className="truncate">{p.rotulo} <b className="text-ink-1 font-mono">{p.texto}</b></span>
          </span>
        ))}
      </div>
    </div>
  )
}

/*
 * AMARELOS JOGO A JOGO: os últimos jogos dele, do mais antigo ao mais novo,
 * com a linha de 4,5 tracejada. Tocar na barra mostra o jogo embaixo (no
 * celular não há hover). Acima da linha a barra ganha o verde da marca.
 */
function AmarelosJogoAJogo({ jogos }: { jogos: Jogo[] }) {
  const [sel, setSel] = useState<number | null>(null)
  const teto = Math.max(LINHA_AMARELOS + 1.5, ...jogos.map(j => j.amarelos ?? 0))
  const acima = jogos.filter(j => (j.amarelos ?? 0) > LINHA_AMARELOS).length
  const j = sel != null ? jogos[sel] : null
  return (
    <div className="mx-4 mb-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[11px] font-bold uppercase tracking-wide text-ink-3">Amarelos jogo a jogo</span>
        <span className="text-[11px] text-ink-3">mais de 4,5 em <b className="text-ink-1">{acima} de {jogos.length}</b></span>
      </div>
      <div className="relative mt-3 h-28 flex items-end gap-[2px]" onMouseLeave={() => setSel(null)}>
        <div className="absolute inset-x-0 border-t border-dashed border-ink-4/70 pointer-events-none"
          style={{ bottom: `${(LINHA_AMARELOS / teto) * 100}%` }}>
          <span className="absolute left-0 -top-3.5 text-[10px] font-mono text-ink-4">4,5</span>
        </div>
        {jogos.map((g, i) => {
          const v = g.amarelos ?? 0
          return (
            <button key={g.fixture_id} type="button" onClick={() => setSel(i === sel ? null : i)} onMouseEnter={() => setSel(i)}
              aria-label={`${dm(g.data)} ${g.home_team ?? ''} x ${g.away_team ?? ''}: ${v} amarelos`}
              className="relative flex-1 h-full flex flex-col justify-end items-center">
              <span className={cn('text-[10px] font-mono mb-0.5', sel === i ? 'text-ink-1 font-bold' : 'text-ink-4')}>{v}</span>
              <span className={cn('w-full max-w-[22px] rounded-t-[4px] transition-opacity',
                v > LINHA_AMARELOS ? 'bg-accent' : 'bg-ink-4/70',
                sel != null && sel !== i && 'opacity-40')}
                style={{ height: `${Math.max((v / teto) * 100, 2)}%` }} />
            </button>
          )
        })}
      </div>
      <p className="mt-1.5 min-h-[18px] text-[11px] text-ink-3 truncate">
        {j ? <>{dm(j.data)}, <span className="text-ink-1">{j.home_team} {j.home_goals}-{j.away_goals} {j.away_team}</span>: {j.amarelos} amarelos, {j.faltas ?? '-'} faltas</>
          : 'Toque numa barra pra ver o jogo'}
      </p>
    </div>
  )
}
