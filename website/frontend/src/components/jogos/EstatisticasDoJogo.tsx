import { useEffect, useState } from 'react'
import api from '../../services/api'
import { cn } from '../../lib/cn'
import { ErrorState, Skeleton } from '../ui'
import { TeamLogo } from '../TeamLogo'
import NumeroVivo from '../ui/NumeroVivo'
import { aoVivo } from '../../lib/aoVivo'

/*
 * ABA ESTATÍSTICAS DO RAIO-X (15/10/2026, pedido do usuário: "estatística do
 * jogo em tempo real igual SofaScore, e depois quando finaliza também").
 *
 * Linha a linha, casa à esquerda e fora à direita, com as duas barras saindo
 * do meio · quem tem mais ganha o número destacado. Jogo inteiro, 1º e 2º
 * tempo. Casa no verde da marca e fora no azul, as mesmas cores da
 * probabilidade de vitória da aba Mercados.
 *
 * Custo (ver backend/estatisticas_do_jogo.py): encerrado vem do banco; rolando,
 * do cache que a lista de Jogos já mantém. A tela relê a cada 60s, o mesmo
 * passo do cache do servidor · reler mais rápido não traria número novo.
 */

interface Linha { chave: string; rotulo: string; casa: number; fora: number; pct: boolean }
type Periodo = 'jogo' | '1t' | '2t'
interface Resposta {
  status: string
  elapsed?: number | null
  home_goals?: number | null; away_goals?: number | null
  fonte: 'banco' | 'ao_vivo' | 'cache' | 'nenhuma'
  periodos: Partial<Record<Periodo, Linha[]>>
}

const ROTULO_PERIODO: Record<Periodo, string> = { jogo: 'Jogo', '1t': '1º tempo', '2t': '2º tempo' }

const GRUPOS: { titulo: string; chaves: string[] }[] = [
  { titulo: 'Visão geral', chaves: ['xg', 'chutes', 'chutes_no_gol', 'escanteios', 'faltas', 'amarelos', 'vermelhos'] },
  { titulo: 'Finalizações', chaves: ['chutes_fora', 'chutes_bloqueados', 'chutes_na_area', 'chutes_de_fora'] },
  { titulo: 'Defesa', chaves: ['defesas', 'desarmes', 'interceptacoes', 'impedimentos'] },
  // Da folha dos jogadores: só aparece depois que o jogo encerrado é coletado.
  { titulo: 'Duelos', chaves: ['duelos_ganhos', 'dribles_certos'] },
  { titulo: 'Passes', chaves: ['passes', 'passes_certos', 'passes_decisivos'] },
]

const formatar = (v: number, pct: boolean) =>
  pct ? `${v}%` : v.toLocaleString('pt-BR', { maximumFractionDigits: 2 })

export default function EstatisticasDoJogo({ fixtureId, homeId, awayId, homeNome, awayNome }: {
  fixtureId: number; homeId?: number; awayId?: number; homeNome?: string; awayNome?: string
}) {
  const [r, setR] = useState<Resposta | null>(null)
  const [erro, setErro] = useState(false)
  const [periodo, setPeriodo] = useState<Periodo>('jogo')
  const [tentativa, setTentativa] = useState(0)

  useEffect(() => {
    let vivo = true
    let timer: ReturnType<typeof setTimeout> | undefined
    setErro(false)
    const ler = () => {
      if (document.hidden) { timer = setTimeout(ler, 60_000); return }
      api.get(`/live/fixture/${fixtureId}/estatisticas`)
        .then(res => {
          if (!vivo) return
          setR(res.data)
          // Só o jogo rolando muda; encerrado e não começado param aqui.
          if (aoVivo(res.data?.status)) timer = setTimeout(ler, 60_000)
        })
        .catch(() => { if (vivo) setErro(true) })
    }
    ler()
    return () => { vivo = false; clearTimeout(timer) }
  }, [fixtureId, tentativa])

  if (erro && !r) {
    return <div className="card"><ErrorState title="Não deu pra carregar as estatísticas" onRetry={() => setTentativa(t => t + 1)} /></div>
  }
  if (!r) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  const disponiveis = (['jogo', '1t', '2t'] as Periodo[]).filter(p => r.periodos[p]?.length)
  if (!disponiveis.length) {
    const naoComecou = !aoVivo(r.status) && !['FT', 'AET', 'PEN'].includes(r.status)
    return (
      <div className="card p-8 text-center">
        <p className="text-sm text-ink-2">
          {naoComecou ? 'As estatísticas aparecem aqui quando a bola rolar.'
                      : 'O provedor ainda não publicou as estatísticas deste jogo.'}
        </p>
        {!naoComecou && <p className="text-xs text-ink-4 mt-1.5">Algumas ligas publicam só depois do apito.</p>}
      </div>
    )
  }

  const atual = disponiveis.includes(periodo) ? periodo : 'jogo'
  const linhas = r.periodos[atual] ?? []
  const porChave = new Map(linhas.map(l => [l.chave, l]))
  const posse = porChave.get('posse')
  const rolando = aoVivo(r.status)

  return (
    <div className="space-y-3">
      {disponiveis.length > 1 && (
        <div className="grid rounded-lg border border-line p-0.5 bg-surface-1"
          style={{ gridTemplateColumns: `repeat(${disponiveis.length}, minmax(0, 1fr))` }}>
          {disponiveis.map(p => (
            <button key={p} type="button" aria-pressed={atual === p} onClick={() => setPeriodo(p)}
              className={cn('h-10 rounded-md text-sm font-bold transition-colors',
                atual === p ? 'bg-surface-3 text-ink-1' : 'text-ink-3')}>
              {ROTULO_PERIODO[p]}
            </button>
          ))}
        </div>
      )}

      <section className="card overflow-hidden">
        {/* Quem é quem: o escudo marca a cor de cada lado, então a cor nunca
            é a única pista de qual barra é de quem. */}
        <div className="px-4 pt-3 pb-2 flex items-center gap-2 text-xs font-bold text-ink-2">
          <span className="w-2 h-2 rounded-full bg-accent" aria-hidden />
          <TeamLogo id={homeId} name={homeNome ?? ''} size={18} />
          <span className="truncate">{homeNome}</span>
          <span className="ml-auto truncate text-right">{awayNome}</span>
          <TeamLogo id={awayId} name={awayNome ?? ''} size={18} />
          <span className="w-2 h-2 rounded-full bg-sky-400" aria-hidden />
        </div>

        {posse && (
          <div className="px-4 pb-4">
            <div className="text-center text-[11px] font-bold uppercase tracking-wide text-ink-3 mb-1.5">Posse de bola</div>
            <div className="flex items-center gap-3">
              <span className="font-mono font-black text-2xl text-ink-1 min-w-[3.5rem] whitespace-nowrap">
                {rolando ? <NumeroVivo valor={posse.casa} /> : posse.casa}%
              </span>
              <div className="flex-1 flex h-2.5 gap-0.5 rounded-full overflow-hidden"
                role="img" aria-label={`Posse: ${homeNome} ${posse.casa}%, ${awayNome} ${posse.fora}%`}>
                <span className="bg-accent rounded-l-full transition-[width] duration-700" style={{ width: `${posse.casa}%` }} />
                <span className="bg-sky-400 rounded-r-full flex-1" />
              </div>
              <span className="font-mono font-black text-2xl text-ink-1 min-w-[3.5rem] whitespace-nowrap text-right">
                {rolando ? <NumeroVivo valor={posse.fora} /> : posse.fora}%
              </span>
            </div>
          </div>
        )}

        {GRUPOS.map(g => {
          const doGrupo = g.chaves.map(c => porChave.get(c)).filter((l): l is Linha => !!l)
          if (!doGrupo.length) return null
          return (
            <div key={g.titulo} className="border-t border-line/60 px-4 py-3">
              <div className="text-[11px] font-bold uppercase tracking-wide text-ink-3 mb-2">{g.titulo}</div>
              <ul className="space-y-3">
                {doGrupo.map(l => <LinhaDeEstatistica key={l.chave} l={l} rolando={rolando} />)}
              </ul>
            </div>
          )
        })}
      </section>

      <p className="text-[11px] text-ink-4 px-1">
        {r.fonte === 'ao_vivo' ? 'Ao vivo, atualiza a cada minuto. ' : ''}
        Fonte: API-Football. Algumas ligas não publicam todos os números (o xG, por exemplo).
      </p>
    </div>
  )
}

function LinhaDeEstatistica({ l, rolando }: { l: Linha; rolando: boolean }) {
  const total = l.casa + l.fora
  // Percentual de passe não soma: cada barra vai até o próprio valor.
  const pCasa = l.pct ? l.casa : total ? (l.casa / total) * 100 : 0
  const pFora = l.pct ? l.fora : total ? (l.fora / total) * 100 : 0
  const casaNaFrente = l.casa > l.fora, foraNaFrente = l.fora > l.casa
  // O número que rola só pra contagem inteira: NumeroVivo escreve decimal com
  // ponto ("1.84"), e o xG tem que sair com vírgula.
  const valor = (v: number) => rolando && !l.pct && Number.isInteger(v) ? <NumeroVivo valor={v} /> : formatar(v, l.pct)

  return (
    <li title={`${l.rotulo}: ${formatar(l.casa, l.pct)} x ${formatar(l.fora, l.pct)}`}>
      <div className="flex items-center justify-between gap-2">
        <span className={cn('min-w-[40px] px-1.5 py-0.5 rounded-md text-sm font-bold tabular-nums',
          casaNaFrente ? 'bg-accent/15 text-ink-1' : 'text-ink-3')}>
          {valor(l.casa)}
        </span>
        <span className="text-[13px] text-ink-2 text-center">{l.rotulo}</span>
        <span className={cn('min-w-[40px] px-1.5 py-0.5 rounded-md text-sm font-bold tabular-nums text-right',
          foraNaFrente ? 'bg-sky-400/15 text-ink-1' : 'text-ink-3')}>
          {valor(l.fora)}
        </span>
      </div>
      <div className="mt-1.5 grid grid-cols-2 gap-1" aria-hidden>
        <span className="h-1.5 rounded-full bg-surface-3 overflow-hidden flex justify-end">
          <span className={cn('h-full rounded-full transition-[width] duration-700', casaNaFrente ? 'bg-accent' : 'bg-accent/45')}
            style={{ width: `${Math.min(100, pCasa)}%` }} />
        </span>
        <span className="h-1.5 rounded-full bg-surface-3 overflow-hidden">
          <span className={cn('block h-full rounded-full transition-[width] duration-700', foraNaFrente ? 'bg-sky-400' : 'bg-sky-400/45')}
            style={{ width: `${Math.min(100, pFora)}%` }} />
        </span>
      </div>
    </li>
  )
}
