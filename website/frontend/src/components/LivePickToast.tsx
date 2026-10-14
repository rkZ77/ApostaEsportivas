import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import { useNotifications } from '../context/NotificationContext'
import { rotuloDoMercado } from '../utils/marketTranslate'
import { LiveDot } from './ui'
import CartaoDeAviso, { timesDoAviso } from './ui/CartaoDeAviso'

/*
 * "O motor achou um pick ao vivo agora" · aviso EM TELA.
 *
 * O evento já existia e já chegava em dois lugares: no sino, e na bandeja do
 * sistema operacional (NotificationContext::avisarPickNovoDoMotor). Faltava o
 * terceiro, que é o mais provável de ser visto: quem está com o site aberto,
 * em outra página dele, agora.
 *
 * POR QUE A BANDEJA DO SISTEMA NÃO RESOLVIA
 * Ela depende de `Notification.permission === 'granted'`, e essa permissão é
 * a que mais gente nega · e, no celular com o navegador em primeiro plano,
 * várias plataformas nem entregam. O resultado era um pick de janela curta
 * publicado enquanto a pessoa navegava na Banca, sem nada na tela dela.
 *
 * DISPENSAR NÃO MARCA COMO LIDO. O item continua no sino: fechar o aviso é
 * "vi", não "resolvi". Quem clicar em "Ver pick" vai pra aba, que é onde a
 * decisão acontece.
 *
 * CARTÃO NO CANTO (11/10/2026, pedido do usuário). Era uma faixa fina no
 * rodapé, com o jogo e o mercado truncados numa linha e um "x" pequeno demais
 * pro dedo. Virou o CartaoDeAviso: quadrado no canto, jogo em destaque,
 * botão de fechar grande e arrastar pro lado no celular.
 *
 * VERDE, E NÃO VERMELHO (2026-09-12, pedido do usuário): vermelho neste site
 * é RED de pick. Em 11/10/2026 saiu o vermelho que sobrava (o ponto pulsante
 * e o selinho sobre a logo): o aviso do ao vivo é todo verde.
 */

/** Quanto tempo o aviso fica. A odd ao vivo dura minutos; o convite, menos. */
const TEMPO_EM_TELA = 25_000

/** Onde ele não entra · na própria aba o pick já aparece na lista. */
const FORA_DE = ['/checkout', '/login']

/** "Pick ao vivo: Flamengo x Palmeiras" → "Flamengo x Palmeiras". O selo do
 *  cartão já diz que é ao vivo; repetir no título gastava a linha mais lida. */
export function jogoDoTitulo(titulo: string): string {
  return titulo.replace(/^pick ao vivo:\s*/i, '').trim() || titulo
}

/** O corpo do aviso vem pronto do servidor (notificar_pick_live_novo):
 *  "Escanteios Over 9.5 @ 1.85 (criado aos 34')". Separado em partes, a odd
 *  vira o número grande do cartão · é ela que vence em minutos. Formato que
 *  não casa volta inteiro em `mercado`, sem odd. */
export function partesDoCorpo(corpo: string | null | undefined): {
  mercado: string | null; odd: string | null; minuto: string | null
} {
  if (!corpo) return { mercado: null, odd: null, minuto: null }
  const m = corpo.match(/^(.*?)\s*@\s*([\d.,]+)\s*(?:\(criado aos (\d+)'\))?\s*$/i)
  if (!m) return { mercado: corpo, odd: null, minuto: null }
  return { mercado: m[1].trim() || null, odd: m[2], minuto: m[3] ?? null }
}

/** "Gols Mais/Menos Under 2.75" → "Gols, Menos de 2.75" (14/10/2026): o
 *  servidor manda mercado e linha colados e em inglês. Fora do formato, volta
 *  como veio. */
export function mercadoLegivel(texto: string | null | undefined): string | null {
  if (!texto) return null
  const m = texto.match(/^(.*?)\s+((?:over|under|mais de|menos de)\s+[\d.,]+)$/i)
  if (!m) return texto
  return rotuloDoMercado(m[1], m[2]).replace(/\s*Mais\/Menos/i, '') || texto
}

export default function LivePickToast() {
  const { livePickNovo, dismissLivePickNovo } = useNotifications()
  const { pathname, hash } = useLocation()
  const navigate = useNavigate()
  const [visivel, setVisivel] = useState(false)

  const naAbaAoVivo = pathname === '/picks' && hash === '#ao_vivo'
  const bloqueado = FORA_DE.some(r => pathname.startsWith(r)) || naAbaAoVivo

  useEffect(() => {
    setVisivel(!!livePickNovo && !bloqueado)
  }, [livePickNovo?.id, bloqueado])

  const fechar = () => { setVisivel(false); dismissLivePickNovo() }

  const abrir = () => {
    fechar()
    /* `navigate` e não <Link>: a aba é um hash da mesma rota, e o React Router
       não remonta a página quando só o hash muda · Picks.tsx lê o hash no
       mount. Navegar explicitamente garante que a aba troque mesmo se a pessoa
       já estiver em /picks noutra aba interna. */
    navigate(livePickNovo?.url || '/picks#ao_vivo')
  }

  const partes = partesDoCorpo(livePickNovo?.body)

  return (
    <AnimatePresence>
      {visivel && livePickNovo && (
        <CartaoDeAviso
          key={livePickNovo.id}
          tom="ao_vivo"
          urgente
          selo="Pick ao vivo"
          icone={<LiveDot tone="green" className="w-1.5 h-1.5" />}
          titulo={jogoDoTitulo(livePickNovo.title)}
          times={timesDoAviso(jogoDoTitulo(livePickNovo.title), livePickNovo.payload)}
          texto={mercadoLegivel(partes.mercado)}
          destaque={partes.odd && (
            <div className="flex items-baseline gap-2">
              <span className="text-[11px] font-bold uppercase tracking-wide text-ink-3">Odd</span>
              <span className="text-2xl font-black text-accent-ink leading-none tabular-nums">{partes.odd}</span>
              {partes.minuto && (
                <span className="text-[11px] text-ink-3 truncate">aos {partes.minuto}'</span>
              )}
            </div>
          )}
          acao={{ rotulo: 'Ver pick', onClick: abrir }}
          onFechar={fechar}
          duracaoMs={TEMPO_EM_TELA}
        />
      )}
    </AnimatePresence>
  )
}
