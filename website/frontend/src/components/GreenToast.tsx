import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import { CheckCircle2, Trophy } from 'lucide-react'
import { useNotifications } from '../context/NotificationContext'
import { fmtBRL } from '../utils/format'
import CartaoDeAviso from './ui/CartaoDeAviso'

/*
 * "Deu GREEN" · aviso EM TELA (11/10/2026, pedido do usuário).
 *
 * O resultado do pick seguido já chegava no sino, no push do celular e no
 * WhatsApp. Quem estava com o site aberto não via nada até abrir o sino · e o
 * GREEN é o aviso que a pessoa mais quer ver na hora.
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

/** Cashout abaixo da stake pode fechar GREEN com lucro negativo: o sinal
 *  acompanha o número (fmtBRL devolve sempre o valor absoluto). */
const sinal = (v: unknown) => (Number(v) < 0 ? '−' : '+')

export default function GreenToast() {
  const { greenNovo, greensJuntos, dismissGreenNovo, markRead } = useNotifications()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const [visivel, setVisivel] = useState(false)

  const bloqueado = FORA_DE.some(r => pathname.startsWith(r))

  useEffect(() => {
    setVisivel(!!greenNovo && !bloqueado)
  }, [greenNovo?.id, bloqueado])

  const fechar = () => { setVisivel(false); dismissGreenNovo() }

  const abrir = () => {
    if (greenNovo) markRead(greenNovo.id)
    fechar()
    navigate(greenNovo?.url || '/banca')
  }

  const pnl = greenNovo?.payload?.pnl
  const unidades = greenNovo?.payload?.profit_units
  const meio = String(greenNovo?.payload?.result || '').toUpperCase() === 'HALF-WIN'
  const mercado = mercadoDoResultado(greenNovo?.body)

  return (
    <AnimatePresence>
      {visivel && greenNovo && (
        <CartaoDeAviso
          key={greenNovo.id}
          tom="green"
          selo={<><CheckCircle2 className="w-3.5 h-3.5" aria-hidden="true" /> {meio ? 'Meio green' : 'Green'}</>}
          icone={<Trophy className="w-5 h-5" aria-hidden="true" />}
          titulo={jogoDoResultado(greenNovo.title)}
          texto={greensJuntos > 0
            ? `${mercado ? `${mercado} · ` : ''}e mais ${greensJuntos} ${greensJuntos === 1 ? 'green' : 'greens'}`
            : mercado}
          destaque={(pnl != null || unidades != null) && (
            <div>
              <p className="text-[11px] font-bold uppercase tracking-wide text-ink-3">Você ganhou</p>
              <p className="text-3xl font-black text-accent-ink leading-none tabular-nums">
                {pnl != null ? `${sinal(pnl)}${fmtBRL(Number(pnl))}` : `${sinal(unidades)}${Math.abs(Number(unidades)).toFixed(2)}u`}
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
