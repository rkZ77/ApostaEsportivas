import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Clock, Cross, HelpCircle, UserX } from 'lucide-react'
import api from '../../services/api'
import { cn } from '../../lib/cn'
import { ErrorState, Skeleton } from '../ui'
import { PlayerPhoto, TeamLogo } from '../TeamLogo'

/*
 * Campinho do Raio-X (2026-10-07, pedido do usuário).
 *
 * A formação desenhada no campo, com os prováveis titulares enquanto a
 * escalação oficial não sai (selo "Provável", âmbar) e a oficial quando sai
 * (selo "Confirmada", verde). Desfalques embaixo, e o titular provável que
 * está no boletim médico ganha contorno vermelho no próprio campo.
 *
 * Campo VERTICAL: é o que cabe no celular sem encolher ninguém. Ataque em
 * cima, goleiro embaixo. Ver backend/escalacao.py pra origem de cada dado.
 */

interface JogadorCampo {
  player_id: number
  nome: string
  numero?: number | null
  posicao?: string | null
  grid?: string | null
  desfalque?: boolean
}

interface TimeCampo {
  status: 'oficial' | 'provavel' | 'indisponivel'
  formacao?: string | null
  tecnico?: string | null
  titulares?: JogadorCampo[]
  reservas?: JogadorCampo[]
}

interface Desfalque { player_id: number; nome: string; categoria: string; motivo: string }

interface Escalacao {
  times: { home: TimeCampo; away: TimeCampo }
  desfalques: { home: Desfalque[]; away: Desfalque[] }
}

const ORDEM_POSICAO: Record<string, number> = { G: 0, D: 1, M: 2, A: 3 }

/**
 * As linhas do campo, do goleiro pro ataque.
 *
 * Oficial: o provedor diz a linha e a coluna de cada um (`grid` "2:3").
 * Provável: não há grid · distribui pela formação ("4-3-3" = 4, 3, 3 depois
 * do goleiro), na ordem de posição; sem formação, agrupa pela posição.
 */
export function linhasDoCampo(titulares: JogadorCampo[], formacao?: string | null): JogadorCampo[][] {
  if (titulares.length && titulares.every(j => j.grid && /^\d+:\d+$/.test(j.grid))) {
    const porLinha = new Map<number, JogadorCampo[]>()
    for (const j of titulares) {
      const [l] = j.grid!.split(':').map(Number)
      porLinha.set(l, [...(porLinha.get(l) ?? []), j])
    }
    return [...porLinha.keys()].sort((a, b) => a - b).map(l =>
      porLinha.get(l)!.sort((a, b) => Number(a.grid!.split(':')[1]) - Number(b.grid!.split(':')[1])))
  }
  const ordenados = [...titulares].sort(
    (a, b) => (ORDEM_POSICAO[a.posicao ?? ''] ?? 9) - (ORDEM_POSICAO[b.posicao ?? ''] ?? 9))
  const blocos = (formacao ?? '').split('-').map(Number).filter(n => n > 0)
  if (blocos.length && 1 + blocos.reduce((a, b) => a + b, 0) === ordenados.length) {
    const linhas: JogadorCampo[][] = [ordenados.slice(0, 1)]
    let i = 1
    for (const n of blocos) { linhas.push(ordenados.slice(i, i + n)); i += n }
    return linhas
  }
  const grupos = new Map<number, JogadorCampo[]>()
  for (const j of ordenados) {
    const k = ORDEM_POSICAO[j.posicao ?? ''] ?? 2
    grupos.set(k, [...(grupos.get(k) ?? []), j])
  }
  return [...grupos.keys()].sort().map(k => grupos.get(k)!)
}

/** "Gabriel Barbosa" -> "Barbosa"; "G. Barbosa" -> "Barbosa". */
const sobrenome = (nome: string) => {
  const partes = nome.trim().split(/\s+/)
  return partes.length > 1 ? partes[partes.length - 1] : nome
}

function Jogador({ j, status }: { j: JogadorCampo; status: TimeCampo['status'] }) {
  const anel = j.desfalque ? 'ring-red-500' : status === 'oficial' ? 'ring-green-500' : 'ring-amber-400'
  return (
    <div className="flex flex-col items-center gap-0.5 w-16 min-w-0" title={j.desfalque ? `${j.nome} · no boletim médico` : j.nome}>
      <div className={cn('relative rounded-full ring-2', anel)}>
        <PlayerPhoto id={j.player_id} name={j.nome} size={38} />
        {j.numero != null && (
          <span className="absolute -bottom-1 -right-1 min-w-[18px] h-[18px] px-0.5 rounded-full bg-surface-0 border border-line text-[9px] font-black text-ink-1 grid place-items-center tabular-nums">
            {j.numero}
          </span>
        )}
        {j.desfalque && (
          <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-red-500 grid place-items-center">
            <Cross size={10} className="text-white" strokeWidth={3} />
          </span>
        )}
      </div>
      <span className="max-w-full truncate text-[10px] font-semibold text-white bg-black/45 rounded px-1 leading-4">
        {sobrenome(j.nome)}
      </span>
    </div>
  )
}

function Campo({ time }: { time: TimeCampo }) {
  const linhas = useMemo(() => linhasDoCampo(time.titulares ?? [], time.formacao), [time])
  return (
    <div className="relative rounded-lg overflow-hidden aspect-[3/4] max-h-[560px] mx-auto w-full
                    bg-[repeating-linear-gradient(180deg,#15803d_0,#15803d_10%,#166534_10%,#166534_20%)]">
      {/* Linhas do campo, em branco translúcido · só desenho, sem dado. */}
      <div aria-hidden className="absolute inset-2 border-2 border-white/35 rounded-sm" />
      <div aria-hidden className="absolute left-2 right-2 top-1/2 border-t-2 border-white/35" />
      <div aria-hidden className="absolute left-1/2 top-1/2 w-20 h-20 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white/35" />
      <div aria-hidden className="absolute left-1/2 bottom-2 w-[55%] h-[16%] -translate-x-1/2 border-2 border-b-0 border-white/35" />
      <div aria-hidden className="absolute left-1/2 top-2 w-[55%] h-[16%] -translate-x-1/2 border-2 border-t-0 border-white/35" />

      {/* Ataque em cima, goleiro embaixo: as linhas vêm do goleiro, então invertidas. */}
      <div className="absolute inset-0 flex flex-col-reverse justify-around py-4">
        {linhas.map((linha, i) => (
          <div key={i} className="flex justify-around items-center px-1">
            {linha.map(j => <Jogador key={j.player_id} j={j} status={time.status} />)}
          </div>
        ))}
      </div>
    </div>
  )
}

const ICONE_DESFALQUE: Record<string, JSX.Element> = {
  lesao: <span className="w-6 h-6 rounded-full bg-red-500/15 grid place-items-center"><Cross size={13} className="text-red-400" strokeWidth={3} /></span>,
  suspenso: <span className="w-6 h-6 grid place-items-center"><span className="w-3 h-4 rounded-[2px] bg-yellow-400" /></span>,
  duvida: <span className="w-6 h-6 rounded-full bg-amber-400/15 grid place-items-center"><HelpCircle size={14} className="text-amber-400" /></span>,
  outro: <span className="w-6 h-6 rounded-full bg-surface-3 grid place-items-center"><UserX size={13} className="text-ink-3" /></span>,
}

export default function Campinho({ fixtureId, homeId, awayId, homeNome, awayNome }: {
  fixtureId: number; homeId: number; awayId: number; homeNome: string; awayNome: string
}) {
  const [dados, setDados] = useState<Escalacao | null>(null)
  const [erro, setErro] = useState(false)
  const [lado, setLado] = useState<'home' | 'away'>('home')

  const carregar = () => {
    setErro(false)
    api.get(`/fixtures/${fixtureId}/escalacao`, { params: { home: homeId, away: awayId } })
      .then(r => setDados(r.data))
      .catch(() => setErro(true))
  }
  useEffect(carregar, [fixtureId])

  if (erro) return <div className="card"><ErrorState title="Não deu pra carregar a escalação" onRetry={carregar} /></div>
  if (!dados) return <div className="space-y-3"><Skeleton className="h-12 w-full" /><Skeleton className="h-[420px] w-full" /></div>

  const time = dados.times[lado]
  const desfalques = dados.desfalques[lado]

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2">
        {(['home', 'away'] as const).map(t => {
          const st = dados.times[t].status
          return (
            <button key={t} onClick={() => setLado(t)}
              className={cn('h-12 rounded-lg border flex items-center justify-center gap-2 px-2 text-sm font-bold transition-colors min-w-0',
                lado === t ? 'bg-surface-2 border-line-strong text-ink-1' : 'bg-surface-1 border-line text-ink-3')}>
              <TeamLogo id={t === 'home' ? homeId : awayId} name="" size={22} />
              <span className="truncate">{t === 'home' ? homeNome : awayNome}</span>
              {st === 'oficial' && <CheckCircle2 size={14} className="text-accent-ink shrink-0" />}
            </button>
          )
        })}
      </div>

      <div className={cn('card p-3 flex items-center gap-3',
        time.status === 'oficial' ? 'border-green-500/40 bg-green-500/5' : time.status === 'provavel' ? 'border-amber-400/30' : '')}>
        {time.status === 'oficial'
          ? <CheckCircle2 className="text-accent-ink shrink-0" size={22} />
          : <Clock className={cn('shrink-0', time.status === 'provavel' ? 'text-amber-400' : 'text-ink-3')} size={22} />}
        <div className="flex-1 min-w-0">
          <div className={cn('text-sm font-bold', time.status === 'oficial' ? 'text-accent-ink' : 'text-ink-1')}>
            {time.status === 'oficial' ? 'Escalação confirmada'
              : time.status === 'provavel' ? 'Escalação provável' : 'Escalação ainda indisponível'}
          </div>
          <div className="text-[11px] text-ink-3">
            {time.status === 'oficial' ? 'Publicada pelo clube.'
              : time.status === 'provavel' ? 'A última que o time usou. A oficial sai de 20 a 40 min antes do jogo.'
              : 'Sem escalação recente desse time no nosso histórico.'}
          </div>
        </div>
        {time.formacao && (
          <span className="font-mono font-black text-lg text-ink-1 tabular-nums shrink-0">{time.formacao}</span>
        )}
      </div>

      {time.titulares?.length ? <Campo time={time} /> : null}

      {time.tecnico && <p className="text-[11px] text-ink-3 px-1">Técnico: <span className="text-ink-2 font-semibold">{time.tecnico}</span></p>}

      <div className="card overflow-hidden">
        <div className="px-4 py-3 border-b border-line flex items-center justify-between">
          <span className="text-sm font-bold text-ink-1">Desfalques</span>
          <span className="text-[11px] text-ink-3">{desfalques.length || 'nenhum informado'}</span>
        </div>
        {desfalques.length === 0 ? (
          <p className="px-4 py-4 text-sm text-ink-3">O clube não informou lesionado nem suspenso pra este jogo.</p>
        ) : (
          <div className="divide-y divide-line/60">
            {desfalques.map(d => (
              <div key={d.player_id} className="px-4 py-2.5 flex items-center gap-3">
                <PlayerPhoto id={d.player_id} name={d.nome} size={32} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold text-ink-1 truncate">{d.nome}</div>
                  <div className="text-[11px] text-ink-3">{d.motivo}</div>
                </div>
                {ICONE_DESFALQUE[d.categoria] ?? ICONE_DESFALQUE.outro}
              </div>
            ))}
          </div>
        )}
      </div>

      {time.status === 'oficial' && (time.reservas?.length ?? 0) > 0 && (
        <div className="card p-4">
          <div className="text-sm font-bold text-ink-1 mb-2">Banco</div>
          <div className="flex flex-wrap gap-1.5">
            {time.reservas!.map(r => (
              <span key={r.player_id} className="text-xs text-ink-2 bg-surface-2 border border-line rounded-full px-2.5 py-1">
                {r.numero != null && <span className="font-mono text-ink-3 mr-1">{r.numero}</span>}{r.nome}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
