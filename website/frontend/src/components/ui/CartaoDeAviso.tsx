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
 *  - QUADRADO no desktop (300x300), com o jogo em destaque e o detalhe embaixo;
 *    no celular, largura da tela menos as margens e altura do conteúdo, pra
 *    não cobrir meia página.
 *  - FECHAR GRANDE: botão de 40px no canto, e no celular dá pra arrastar o
 *    cartão pro lado. Fechar NÃO marca como lido: o item continua no sino.
 *  - TEMPO VISÍVEL: a barra de baixo mostra quanto falta pra ele sair sozinho,
 *    e o tempo para enquanto o mouse está em cima (ninguém perde o aviso no
 *    meio da leitura).
 */

export type TomDoAviso = 'ao_vivo' | 'green' | 'red' | 'neutro'

const TOM: Record<TomDoAviso, { borda: string; selo: string; barra: string; icone: string }> = {
  // `icone` é o selinho sobre a logo: preenchido, pra ler a 20px.
  ao_vivo: { borda: 'border-accent/50',   selo: 'bg-red-500/15 text-red-400',     barra: 'bg-accent',   icone: 'bg-red-600 text-white' },
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
    <span className="relative w-9 h-9 shrink-0 grid place-items-center">
      {(!src || falhou) && (
        <span className="w-9 h-9 rounded-full bg-surface-3 grid place-items-center text-[11px] font-black text-ink-3">
          {iniciais}
        </span>
      )}
      {src && !falhou && (
        <img src={src} alt="" width={36} height={36} className="w-9 h-9 object-contain"
          onError={() => setFalhou(true)} />
      )}
    </span>
  )
}

/** "Flamengo  x  Fluminense" com o escudo em cima de cada nome. */
function LinhaDosTimes({ casa, fora, casaId, foraId }: TimesDoAviso) {
  return (
    <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2" aria-label={`${casa} x ${fora}`}>
      {[{ nome: casa, id: casaId }, null, { nome: fora, id: foraId }].map((t, i) => t ? (
        <span key={i} className="flex flex-col items-center gap-1 min-w-0">
          <EscudoDoAviso id={t.id} nome={t.nome} />
          <span className="w-full text-center text-[13px] font-black text-ink-1 leading-tight truncate">{t.nome}</span>
        </span>
      ) : (
        <span key={i} className="text-sm font-black text-ink-4 pb-5">x</span>
      ))}
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
      className={cn(
        'pointer-events-auto relative w-full sm:w-[300px] sm:aspect-square',
        'bg-surface-1 border rounded-2xl shadow-2xl overflow-hidden',
        'flex flex-col touch-pan-y select-none',
        cores.borda,
      )}
    >
      <div className="flex items-center justify-between gap-2 pl-3 pr-2 pt-3">
        <div className="flex items-center gap-2.5 min-w-0">
          {/* A MARCA COM O SELINHO (11/10/2026, pedido do usuário): a logo da
              PickIA no lugar do ícone genérico, e o status (✓, ✗, ao vivo)
              num selinho por cima dela · o aviso diz de quem é e o que foi. */}
          <span className="relative shrink-0 w-10 h-10">
            <img src="/logo-64.webp" alt="PickIA" width={40} height={40}
              className="w-10 h-10 rounded-full object-cover" />
            <span className={cn('absolute -bottom-1 -right-1 w-5 h-5 rounded-full ring-2 ring-surface-1',
                                'flex items-center justify-center', cores.icone)}>
              {icone}
            </span>
          </span>
          <span className="flex flex-col items-start gap-1 min-w-0">
            <span className="text-[13px] font-black text-ink-1 leading-none">PickIA</span>
            <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-black uppercase tracking-wide', cores.selo)}>
              {selo}
            </span>
          </span>
        </div>
        <button
          type="button"
          onClick={onFechar}
          aria-label="Fechar aviso"
          className="w-10 h-10 -mt-1 shrink-0 flex items-center justify-center rounded-full
                     text-ink-2 hover:text-ink-1 hover:bg-surface-3 active:bg-surface-3 transition-colors"
        >
          <X className="w-5 h-5" aria-hidden="true" />
        </button>
      </div>

      <div className="flex-1 flex flex-col px-4 pt-3 pb-4 gap-2.5 min-h-0">
        <div className="min-w-0">
          {times
            ? <LinhaDosTimes {...times} />
            : <p className="text-[15px] font-black text-ink-1 leading-snug line-clamp-2 break-words">{titulo}</p>}
          {texto && (
            <p className={cn('mt-1 text-[13px] text-ink-2 leading-snug line-clamp-2 break-words', times && 'text-center')}>
              {texto}
            </p>
          )}
        </div>

        {destaque && <div className="sm:flex-1 flex items-center">{destaque}</div>}

        {acao && (
          <button
            type="button"
            onClick={acao.onClick}
            className={cn(
              'mt-auto w-full min-h-[44px] rounded-xl text-sm font-black transition-colors',
              tom === 'red' || tom === 'neutro'
                ? 'bg-surface-3 hover:bg-surface-2 text-ink-1'
                : 'bg-accent hover:bg-accent-hover active:bg-accent-press text-on-fill',
            )}
          >
            {acao.rotulo}
          </button>
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
