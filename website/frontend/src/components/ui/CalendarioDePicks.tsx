import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react'

/*
 * Escolha de DIA num calendário, com os dias que tiveram pick marcados.
 *
 * Substitui o par de setas "‹ Hoje ›" que vivia na barra do topo. Duas coisas
 * o condenavam:
 *
 *   - navegar era um clique POR DIA. Voltar duas semanas custava catorze
 *     cliques, e cada um deles disparava uma busca no servidor.
 *   - ele não dizia onde havia o que ver. A pessoa clicava no vazio sem saber,
 *     e um dia sem pick é indistinguível de um dia que ainda não carregou.
 *
 * Aqui o mês inteiro aparece de uma vez e os dias com pick vêm em verde: a
 * escolha passa a ser sobre o que existe, não sobre o calendário.
 *
 * O verde sai de `diasComPick`, que é o `by_day` do placar público -- o mesmo
 * dado que a página de Resultados desenha. Sem ele o calendário continua
 * funcionando, só sem a marca: dia sem informação não é pintado de cinza (isso
 * afirmaria que não teve pick), ele fica igual a qualquer outro.
 */

const DIAS = ['D', 'S', 'T', 'Q', 'Q', 'S', 'S']

/** "YYYY-MM-DD" de hoje em Brasília. en-CA devolve exatamente nessa ordem. */
export const hojeISO = () =>
  new Date().toLocaleDateString('en-CA', { timeZone: 'America/Sao_Paulo' })

const iso = (ano: number, mes: number, dia: number) =>
  `${ano}-${String(mes + 1).padStart(2, '0')}-${String(dia).padStart(2, '0')}`

/** Rótulo curto do botão. Hoje e ontem por nome, o resto por data. */
function rotulo(valor: string): string {
  const hoje = hojeISO()
  if (valor === hoje) return 'Hoje'
  const ontem = new Date(`${hoje}T12:00:00`)
  ontem.setDate(ontem.getDate() - 1)
  if (valor === ontem.toLocaleDateString('en-CA')) return 'Ontem'
  const d = new Date(`${valor}T12:00:00`)
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
}

export default function CalendarioDePicks({
  valor,
  onChange,
  diasComPick,
  /** Último dia escolhível. Padrão: hoje · a tela de picks não olha o futuro. */
  maxISO = hojeISO(),
  className,
}: {
  valor: string
  onChange: (isoDia: string) => void
  diasComPick?: Set<string> | string[]
  maxISO?: string
  className?: string
}) {
  const [aberto, setAberto] = useState(false)
  const [mesAberto, setMesAberto] = useState(() => valor.slice(0, 7))
  const raiz = useRef<HTMLDivElement>(null)

  const marcados = diasComPick instanceof Set
    ? diasComPick
    : new Set(diasComPick ?? [])

  // Reabrir sempre no mês do dia escolhido: quem voltou pra agosto e fechou
  // espera achar agosto de novo, não o mês corrente.
  useEffect(() => { if (aberto) setMesAberto(valor.slice(0, 7)) }, [aberto, valor])

  useEffect(() => {
    if (!aberto) return
    const fora = (e: MouseEvent) => {
      if (raiz.current && !raiz.current.contains(e.target as Node)) setAberto(false)
    }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setAberto(false) }
    document.addEventListener('mousedown', fora)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', fora)
      document.removeEventListener('keydown', esc)
    }
  }, [aberto])

  const [ano, mes] = mesAberto.split('-').map(Number)
  const primeiro = new Date(ano, mes - 1, 1)
  const diasNoMes = new Date(ano, mes, 0).getDate()
  const vazios = primeiro.getDay()
  const nomeDoMes = primeiro
    .toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' })
    .replace(/^./, c => c.toUpperCase())

  const mover = (passo: number) => {
    const d = new Date(ano, mes - 1 + passo, 1)
    setMesAberto(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`)
  }

  const escolher = (dia: string) => {
    if (dia > maxISO) return
    onChange(dia)
    setAberto(false)
  }

  return (
    <div ref={raiz} className={`relative ${className ?? ''}`}>
      <button
        type="button"
        onClick={() => setAberto(a => !a)}
        aria-label="Escolher o dia"
        aria-expanded={aberto}
        className="flex items-center gap-2 px-3 py-2 rounded-md border border-line bg-surface-1
                   text-xs font-semibold text-ink-2 hover:text-ink-1 hover:border-line-strong
                   transition-colors min-h-[36px]"
      >
        <CalendarDays className="w-3.5 h-3.5 text-ink-3 shrink-0" />
        {rotulo(valor)}
      </button>

      <AnimatePresence>
        {aberto && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.12 }}
            className="absolute left-0 top-full mt-1.5 z-40 w-[268px] rounded-lg border border-line
                       bg-surface-1 shadow-xl p-3"
          >
            <div className="flex items-center justify-between mb-2">
              <button
                type="button" onClick={() => mover(-1)} aria-label="Mês anterior"
                className="p-1.5 rounded-md text-ink-3 hover:text-ink-1 hover:bg-surface-2 transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <span className="text-xs font-bold text-ink-1">{nomeDoMes}</span>
              <button
                type="button" onClick={() => mover(1)} aria-label="Próximo mês"
                className="p-1.5 rounded-md text-ink-3 hover:text-ink-1 hover:bg-surface-2 transition-colors"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>

            <div className="grid grid-cols-7 gap-0.5 mb-1">
              {DIAS.map((d, i) => (
                <span key={i} className="text-[10px] text-ink-4 text-center py-1">{d}</span>
              ))}
            </div>

            <div className="grid grid-cols-7 gap-0.5">
              {Array.from({ length: vazios }, (_, i) => <span key={`v${i}`} />)}
              {Array.from({ length: diasNoMes }, (_, i) => {
                const dia = iso(ano, mes - 1, i + 1)
                const futuro = dia > maxISO
                const sel = dia === valor
                const temPick = marcados.has(dia)
                return (
                  <button
                    key={dia}
                    type="button"
                    onClick={() => escolher(dia)}
                    disabled={futuro}
                    aria-current={sel ? 'date' : undefined}
                    title={temPick ? 'Teve pick neste dia' : undefined}
                    className={[
                      'relative h-8 rounded-md text-[11px] font-semibold tabular-nums transition-colors',
                      futuro ? 'text-ink-4/40 cursor-default'
                        : sel ? 'bg-accent text-black'
                          /* Verde no TEXTO, não no fundo: o fundo é do dia
                             escolhido, e dois cheios competindo fariam o
                             selecionado sumir num mês com pick todo dia. */
                          : temPick ? 'text-accent-ink hover:bg-surface-2'
                            : 'text-ink-2 hover:bg-surface-2',
                    ].join(' ')}
                  >
                    {i + 1}
                    {temPick && !sel && (
                      <span className="absolute bottom-1 left-1/2 -translate-x-1/2 w-1 h-1 rounded-full bg-accent" />
                    )}
                  </button>
                )
              })}
            </div>

            <div className="flex items-center justify-between mt-2 pt-2 border-t border-line/60">
              <span className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-accent" />
                <span className="text-[10px] text-ink-4">dia com pick</span>
              </span>
              <button
                type="button"
                onClick={() => escolher(hojeISO())}
                className="text-[10px] font-bold text-accent-ink hover:text-accent-hover transition-colors"
              >
                Hoje
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
