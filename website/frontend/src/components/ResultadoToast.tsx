import { useEffect, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import { CheckCircle2, RotateCcw, Trophy, XCircle } from 'lucide-react'
import { useNotifications } from '../context/NotificationContext'
import { fmtBRL } from '../utils/format'
import CartaoDeAviso, { type TomDoAviso } from './ui/CartaoDeAviso'

/*
 * Resultado do pick seguido · aviso EM TELA (11/10/2026, pedido do usuário).
 *
 * O resultado já chegava no sino, no push do celular e no WhatsApp. Quem
 * estava com o site aberto não via nada até abrir o sino. Começou só com o
 * GREEN; no mesmo dia o pedido virou "todos os resultados": green, red, meio
 * a meio e devolvido, cada um com a sua cor.
 *
 * Mesmo cartão do pick ao vivo, no mesmo canto (ver CartaoDeAviso). O
 * dinheiro é o destaque: é o número dela, com a stake e a odd dela, calculado
 * no servidor (notify_pick_result). Só aparece logado e com o site aberto: o
 * evento vem do poll do sino, que só roda com sessão e com a aba visível.
 *
 * FECHAR NÃO MARCA COMO LIDO, igual ao ao vivo. "Ver na Banca" marca: ali a
 * pessoa foi ver o resultado de fato.
 */

const TEMPO_EM_TELA = 15_000
const FORA_DE = ['/checkout', '/login']

interface Visual { tom: TomDoAviso; selo: string; icone: ReactNode; legenda: string }

const VISUAL: Record<string, Visual> = {
  'GREEN':     { tom: 'green',  selo: 'Green',     icone: <Trophy className="w-5 h-5" aria-hidden="true" />,    legenda: 'Você ganhou' },
  'HALF-WIN':  { tom: 'green',  selo: 'Meio green', icone: <Trophy className="w-5 h-5" aria-hidden="true" />,   legenda: 'Você ganhou' },
  'RED':       { tom: 'red',    selo: 'Red',       icone: <XCircle className="w-5 h-5" aria-hidden="true" />,   legenda: 'Resultado' },
  'HALF-LOSS': { tom: 'red',    selo: 'Meio red',  icone: <XCircle className="w-5 h-5" aria-hidden="true" />,   legenda: 'Resultado' },
  'PUSH':      { tom: 'neutro', selo: 'Devolvido', icone: <RotateCcw className="w-5 h-5" aria-hidden="true" />, legenda: 'Entrada devolvida' },
}

/** O visual de cada resultado. Desconhecido cai no neutro, nunca no verde. */
export function visualDoResultado(resultado: unknown): Visual {
  return VISUAL[String(resultado ?? '').toUpperCase()] ?? VISUAL.PUSH
}

/** "GREEN: Flamengo x Palmeiras" → "Flamengo x Palmeiras" (o selo já diz). */
export function jogoDoResultado(titulo: string): string {
  return titulo.replace(/^(GREEN|HALF-WIN|RED|HALF-LOSS|PUSH)\s*:\s*/i, '').trim() || titulo
}

/** O corpo é "Escanteios Over 9.5 +R$ 12,00 (+0.85u)": o dinheiro sai daqui
 *  porque vira o destaque do cartão, montado do payload. */
export function mercadoDoResultado(corpo: string | null | undefined): string | null {
  if (!corpo) return null
  return corpo.replace(/\s*[+-]?R\$\s?[\d.,]+.*$/, '').replace(/\s*\([+-]?[\d.,]+u\)\s*$/, '').trim() || null
}

/** fmtBRL devolve sempre o valor absoluto: o sinal acompanha o número. */
const sinal = (v: unknown) => (Number(v) < 0 ? '−' : Number(v) > 0 ? '+' : '')

export default function ResultadoToast() {
  const { resultadoNovo, resultadosJuntos, dismissResultadoNovo, markRead } = useNotifications()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const [visivel, setVisivel] = useState(false)

  const bloqueado = FORA_DE.some(r => pathname.startsWith(r))

  useEffect(() => {
    setVisivel(!!resultadoNovo && !bloqueado)
  }, [resultadoNovo?.id, bloqueado])

  const fechar = () => { setVisivel(false); dismissResultadoNovo() }

  const abrir = () => {
    if (resultadoNovo) markRead(resultadoNovo.id)
    fechar()
    navigate(resultadoNovo?.url || '/banca')
  }

  const visual = visualDoResultado(resultadoNovo?.payload?.result)
  const pnl = resultadoNovo?.payload?.pnl
  const unidades = resultadoNovo?.payload?.profit_units
  const mercado = mercadoDoResultado(resultadoNovo?.body)
  const corDoNumero = visual.tom === 'green' ? 'text-accent-ink' : visual.tom === 'red' ? 'text-red-400' : 'text-ink-1'

  return (
    <AnimatePresence>
      {visivel && resultadoNovo && (
        <CartaoDeAviso
          key={resultadoNovo.id}
          tom={visual.tom}
          selo={<>
            {visual.tom === 'green' && <CheckCircle2 className="w-3.5 h-3.5" aria-hidden="true" />}
            {visual.selo}
          </>}
          icone={visual.icone}
          titulo={jogoDoResultado(resultadoNovo.title)}
          texto={resultadosJuntos > 0
            ? `${mercado ? `${mercado} · ` : ''}e mais ${resultadosJuntos} ${resultadosJuntos === 1 ? 'resultado' : 'resultados'}`
            : mercado}
          destaque={(pnl != null || unidades != null) && (
            <div>
              <p className="text-[11px] font-bold uppercase tracking-wide text-ink-3">{visual.legenda}</p>
              <p className={`text-3xl font-black leading-none tabular-nums ${corDoNumero}`}>
                {pnl != null
                  ? `${sinal(pnl)}${fmtBRL(Number(pnl))}`
                  : `${sinal(unidades)}${Math.abs(Number(unidades)).toFixed(2)}u`}
              </p>
              {pnl != null && unidades != null && (
                <p className="mt-1 text-xs text-ink-3 tabular-nums">
                  {sinal(unidades)}{Math.abs(Number(unidades)).toFixed(2)} unidades
                </p>
              )}
            </div>
          )}
          acao={{ rotulo: 'Ver na Banca', onClick: abrir }}
          onFechar={fechar}
          duracaoMs={TEMPO_EM_TELA}
        />
      )}
    </AnimatePresence>
  )
}
