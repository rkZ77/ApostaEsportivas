import { useMemo } from 'react'
import { distribuicaoDeGols, linhasDaLiga, type JogoDaLiga } from '../../lib/linhasDaLiga'

/*
 * TAXA POR LINHA DA LIGA (15/10/2026). Uma barra por linha, uma cor só (é
 * magnitude, não identidade); o número fica na tinta do texto, nunca na cor da
 * barra. "62 de 100" ao lado do percentual pra amostra nunca ficar escondida.
 */
export default function LinhasDaLiga({ jogos }: { jogos: JogoDaLiga[] }) {
  const grupos = useMemo(() => linhasDaLiga(jogos), [jogos])
  const dist = useMemo(() => distribuicaoDeGols(jogos), [jogos])
  const maior = Math.max(1, ...dist.map(d => d.jogos))
  const comPlacar = dist.reduce((s, d) => s + d.jogos, 0)

  return (
    <div className="grid gap-3 lg:grid-cols-[1fr_320px]">
      <section className="card p-4">
        <h3 className="text-sm font-bold text-ink-1">Em quantos jogos a linha bateu</h3>
        <p className="text-[11px] text-ink-3 mt-0.5 mb-3">Mesma amostra dos números acima.</p>
        <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
          {grupos.map(g => (
            <div key={g.titulo}>
              <div className="text-[11px] font-bold uppercase tracking-wide text-ink-3 mb-1.5">{g.titulo}</div>
              <ul className="space-y-1">
                {g.linhas.map(l => (
                  <li key={l.rotulo} className="flex items-center gap-3 min-h-[28px]"
                    title={l.pct == null ? 'Sem dado' : `${l.rotulo}: ${l.bateu} de ${l.total} jogos`}>
                    <span className="w-[104px] shrink-0 text-[13px] text-ink-2">{l.rotulo}</span>
                    <span className="flex-1 h-1.5 rounded-full bg-surface-3 overflow-hidden">
                      <span className="block h-full rounded-full bg-accent" style={{ width: `${l.pct ?? 0}%` }} />
                    </span>
                    <span className="w-10 text-right font-mono font-black text-lg leading-none text-ink-1">
                      {l.pct == null ? '-' : `${l.pct}%`}
                    </span>
                    <span className="hidden min-[400px]:block w-14 text-right font-mono text-[11px] text-ink-4">
                      {l.total ? `${l.bateu}/${l.total}` : ''}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      <section className="card p-4">
        <h3 className="text-sm font-bold text-ink-1">Gols por jogo</h3>
        <p className="text-[11px] text-ink-3 mt-0.5">Quantos jogos terminaram com cada total.</p>
        <div className="mt-4 flex items-end gap-2 h-36" role="img"
          aria-label={dist.map(d => `${d.rotulo} gols: ${d.jogos} jogos`).join(', ')}>
          {dist.map(d => (
            <div key={d.rotulo} className="flex-1 h-full flex flex-col justify-end items-center gap-1"
              title={`${d.rotulo} gols: ${d.jogos} jogos (${comPlacar ? Math.round(d.jogos / comPlacar * 100) : 0}%)`}>
              <span className="font-mono text-[11px] text-ink-2">{d.jogos}</span>
              <span className="w-full max-w-[36px] rounded-t bg-accent/80 hover:bg-accent transition-colors"
                // 18px é o rótulo em cima: a barra mais alta ocupa o resto.
                style={{ height: `calc((100% - 18px) * ${d.jogos / maior})`, minHeight: d.jogos ? 2 : 0 }} />
            </div>
          ))}
        </div>
        <div className="mt-1.5 flex gap-2 border-t border-line pt-1.5">
          {dist.map(d => (
            <span key={d.rotulo} className="flex-1 text-center font-mono font-black text-base text-ink-2">{d.rotulo}</span>
          ))}
        </div>
      </section>
    </div>
  )
}
