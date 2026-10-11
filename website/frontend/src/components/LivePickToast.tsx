import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import { Activity } from 'lucide-react'
import { useNotifications } from '../context/NotificationContext'
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
          selo={<><LiveDot tone="green" className="w-1.5 h-1.5" /> Pick ao vivo</>}
          /* `Activity` e não `Radio`: o que o aviso anuncia é uma partida em
             andamento · a linha de batimento diz jogo correndo. */
          icone={<Activity className="w-3 h-3" strokeWidth={3} aria-hidden="true" />}
          titulo={jogoDoTitulo(livePickNovo.title)}
          times={timesDoAviso(jogoDoTitulo(livePickNovo.title), livePickNovo.payload)}
          texto={partes.mercado}
          destaque={partes.odd && (
            <div className="flex items-end gap-3">
              <div>
                <p className="text-[11px] font-bold uppercase tracking-wide text-ink-3">Odd</p>
                <p className="text-3xl font-black text-accent-ink leading-none tabular-nums">{partes.odd}</p>
              </div>
              {partes.minuto && (
                <p className="text-xs text-ink-3 pb-0.5">criado aos {partes.minuto}'</p>
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
