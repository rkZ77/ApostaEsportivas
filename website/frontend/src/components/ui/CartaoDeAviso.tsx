import { useEffect, useRef, useState, type ReactNode } from 'react'
import { m as motion, type PanInfo } from 'framer-motion'
import { X } from 'lucide-react'
import { cn } from '../../lib/cn'
import { cantoIn } from '../../lib/motion'
import { escudoDoTime } from '../../lib/aoVivo'

/*
 * O CARTÃO QUADRADO DOS AVISOS DE JOGO (11/10/2026, pedido do usuário).
 *
 * A faixa fina de antes (uma linha de texto truncado e um "x" de 28px) lia mal
 * no celular e era difícil de fechar com o dedo. Aqui:
 *
 *  - COMPACTO desde 14/10/2026 (era quadrado de 300x300): 340px no desktop,
 *    largura da tela menos as margens no celular, altura do conteúdo.
 *  - FECHAR: botão de 36px no canto, e no celular dá pra arrastar o
 *    cartão pro lado. Fechar NÃO marca como lido: o item continua no sino.
 *  - TEMPO VISÍVEL: a barra de baixo mostra quanto falta pra ele sair sozinho,
 *    e o tempo para enquanto o mouse está em cima (ninguém perde o aviso no
 *    meio da leitura).
 */

export type TomDoAviso = 'ao_vivo' | 'green' | 'red' | 'neutro'

const TOM: Record<TomDoAviso, { borda: string; selo: string; barra: string; icone: string }> = {
  // `icone` é o selinho sobre a logo: preenchido, pra ler a 20px.
  // Ao vivo SEM vermelho (11/10/2026, pedido do usuário): vermelho aqui é RED
  // de pick, e oportunidade chegando não pode ter cara de derrota.
  ao_vivo: { borda: 'border-accent/50',   selo: 'bg-accent/15 text-accent-ink',   barra: 'bg-accent',   icone: 'bg-accent text-on-fill' },
  green:   { borda: 'border-accent/60',   selo: 'bg-accent/15 text-accent-ink',   barra: 'bg-accent',   icone: 'bg-accent text-on-fill' },
  red:     { borda: 'border-red-500/50',  selo: 'bg-red-500/15 text-red-400',     barra: 'bg-red-500',  icone: 'bg-red-600 text-white' },
  neutro:  { borda: 'border-line-strong', selo: 'bg-surface-3 text-ink-2',        barra: 'bg-ink-3',    icone: 'bg-surface-3 text-ink-1' },
}

export interface TimesDoAviso { casa: string; fora: string; casaId?: number | null; foraId?: number | null }

/** Escudo com as iniciais por baixo: sem id, ou com o escudo falhando, o
 *  lugar não fica vazio (mesma ideia do PlayerPhoto). */
function EscudoDoAviso({ id, nome }: { id?: number | null; nome: string }) {
  const [falhou, setFalhou] = useState(false)
  const src = escudoDoTime(id ?? undefined)
  const iniciais = nome.trim().split(/\s+/).map(p => p[0]).join('').slice(0, 2).toUpperCase() || '?'
  return (
    <span className="relative w-6 h-6 shrink-0 grid place-items-center">
      {(!src || falhou) && (
        <span className="w-6 h-6 rounded-full bg-surface-3 grid place-items-center text-[9px] font-black text-ink-3">
          {iniciais}
        </span>
      )}
      {src && !falhou && (
        <img src={src} alt="" width={24} height={24} className="w-6 h-6 object-contain"
          onError={() => setFalhou(true)} />
      )}
    </span>
  )
}

/** "[escudo] Flamengo  x  Fluminense [escudo]" numa linha só (14/10/2026):
 *  o escudo em cima de cada nome dobrava a altura do aviso. */
function LinhaDosTimes({ casa, fora, casaId, foraId }: TimesDoAviso) {
  return (
    <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2" aria-label={`${casa} x ${fora}`}>
      <span className="flex items-center justify-end gap-1.5 min-w-0">
        <span className="text-[13px] font-black text-ink-1 leading-tight truncate">{casa}</span>
        <EscudoDoAviso id={casaId} nome={casa} />
      </span>
      <span className="text-xs font-black text-ink-4">x</span>
      <span className="flex items-center gap-1.5 min-w-0">
        <EscudoDoAviso id={foraId} nome={fora} />
        <span className="text-[13px] font-black text-ink-1 leading-tight truncate">{fora}</span>
      </span>
    </div>
  )
}

/** "Flamengo x Fluminense" + ids do payload → times do cartão, ou null quando
 *  o título não é um jogo (múltipla, bilhete). */
export function timesDoAviso(jogo: string, payload?: Record<string, any> | null): TimesDoAviso | null {
  const partes = jogo.split(/\s+x\s+/i)
  if (partes.length !== 2 || !partes[0].trim() || !partes[1].trim()) return null
  const id = (v: unknown) => (typeof v === 'number' && v > 0 ? v : null)
  return { casa: partes[0].trim(), fora: partes[1].trim(),
           casaId: id(payload?.home_team_id), foraId: id(payload?.away_team_id) }
}

/** Arrasto lateral que fecha o cartão no celular, em px. */
const ARRASTO_PARA_FECHAR = 90

export interface CartaoDeAvisoProps {
  tom: TomDoAviso
  /** Selo pequeno do topo ("AO VIVO", "GREEN"). */
  selo: ReactNode
  icone: ReactNode
  titulo: string
  /** Os dois times com escudo, no lugar do título (ver timesDoAviso). */
  times?: TimesDoAviso | null
  /** Linha de apoio logo abaixo do título (mercado, linha, odd). */
  texto?: string | null
  /** Destaque grande opcional (o lucro do GREEN). */
  destaque?: ReactNode
  acao?: { rotulo: string; onClick: () => void }
  onFechar: () => void
  /** Some sozinho depois disso. 0 = só fecha na mão. */
  duracaoMs?: number
  /** Leitor de tela: o ao vivo interrompe, o resultado espera a vez. */
  urgente?: boolean
}

export default function CartaoDeAviso({
  tom, selo, icone, titulo, times, texto, destaque, acao, onFechar, duracaoMs = 0, urgente = false,
}: CartaoDeAvisoProps) {
  const cores = TOM[tom]
  const [pausado, setPausado] = useState(false)
  const restante = useRef(duracaoMs)
  const inicio = useRef(Date.now())
  const fecharRef = useRef(onFechar)
  fecharRef.current = onFechar

  /* O relógio sai do tempo que SOBROU, e não do total: pausar e soltar não
     pode reiniciar a contagem, senão quem passa o mouse por cima de vez em
     quando prende o aviso na tela pra sempre. */
  useEffect(() => {
    if (!duracaoMs) return
    if (pausado) {
      restante.current -= Date.now() - inicio.current
      return
    }
    inicio.current = Date.now()
    const t = setTimeout(() => fecharRef.current(), Math.max(0, restante.current))
    return () => clearTimeout(t)
  }, [pausado, duracaoMs])

  const aoSoltar = (_: unknown, info: PanInfo) => {
    if (Math.abs(info.offset.x) > ARRASTO_PARA_FECHAR) onFechar()
  }

  return (
    <motion.div
      variants={cantoIn}
      initial="hidden"
      animate="visible"
      exit="exit"
      drag="x"
      dragConstraints={{ left: 0, right: 0 }}
      dragElastic={0.7}
      dragSnapToOrigin
      onDragEnd={aoSoltar}
      /* Só mouse pausa: no celular o toque emula `mouseenter` e nunca solta,
         o que prenderia o aviso na tela. */
      onPointerEnter={e => { if (e.pointerType === 'mouse') setPausado(true) }}
      onPointerLeave={e => { if (e.pointerType === 'mouse') setPausado(false) }}
      role={urgente ? 'alert' : 'status'}
      aria-live={urgente ? 'assertive' : 'polite'}
      /* COMPACTO (14/10/2026, pedido do usuário: "poderia ser um pouco menor").
         Era um quadrado fixo de 300x300 com espaço sobrando; agora a altura é
         a do conteúdo, e destaque + botão dividem a última linha. */
      className={cn(
        'pointer-events-auto relative w-full sm:w-[340px]',
        'bg-surface-1/95 backdrop-blur border rounded-xl shadow-2xl overflow-hidden',
        'flex flex-col touch-pan-y select-none',
        cores.borda,
      )}
    >
      {/* Marca, selo e fechar NUMA linha: o selo solto embaixo do nome ficava
          "no meio do nada". O ícone de status vai dentro do próprio selo. */}
      <div className="flex items-center gap-2 pl-3 pr-1.5 pt-2">
        <img src="/logo-64.webp" alt="PickIA" width={22} height={22}
          className="w-[22px] h-[22px] rounded-full object-cover shrink-0" />
        <span className="text-xs font-black text-ink-1">PickIA</span>
        <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-black uppercase tracking-wide min-w-0',
                            cores.selo)}>
          {icone}{selo}
        </span>
        <button
          type="button"
          onClick={onFechar}
          aria-label="Fechar aviso"
          className="ml-auto w-9 h-9 shrink-0 flex items-center justify-center rounded-full
                     text-ink-3 hover:text-ink-1 hover:bg-surface-3 active:bg-surface-3 transition-colors"
        >
          <X className="w-4 h-4" aria-hidden="true" />
        </button>
      </div>

      <div className="px-3 pb-3 pt-1 space-y-2.5">
        <div className="min-w-0">
          {times
            ? <LinhaDosTimes {...times} />
            : <p className="text-sm font-black text-ink-1 leading-snug line-clamp-2 break-words">{titulo}</p>}
          {texto && (
            <p className={cn('mt-1 text-xs text-ink-2 leading-snug line-clamp-2 break-words', times && 'text-center')}>
              {texto}
            </p>
          )}
        </div>

        {(destaque || acao) && (
          <div className="flex items-center gap-3">
            {destaque && <div className="flex-1 min-w-0">{destaque}</div>}
            {acao && (
              <button
                type="button"
                onClick={acao.onClick}
                className={cn(
                  'shrink-0 h-10 px-4 rounded-lg text-sm font-black transition-colors',
                  !destaque && 'flex-1',
                  tom === 'red' || tom === 'neutro'
                    ? 'bg-surface-3 hover:bg-surface-2 text-ink-1'
                    : 'bg-accent hover:bg-accent-hover active:bg-accent-press text-on-fill',
                )}
              >
                {acao.rotulo}
              </button>
            )}
          </div>
        )}
      </div>

      {duracaoMs > 0 && (
        <div className="h-1 w-full bg-surface-3" aria-hidden="true">
          <div
            className={cn('h-full w-full origin-left motion-reduce:hidden', cores.barra)}
            style={{
              animation: `aviso-encolher ${duracaoMs}ms linear forwards`,
              animationPlayState: pausado ? 'paused' : 'running',
            }}
          />
        </div>
      )}
    </motion.div>
  )
}
