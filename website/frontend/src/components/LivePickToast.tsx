import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Radio, X } from 'lucide-react'
import { useNotifications } from '../context/NotificationContext'
import { LiveDot } from './ui'
import { toastUp } from '../lib/motion'

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
 * DISPENSAR NÃO MARCA COMO LIDO. O item continua no sino: fechar o toast é
 * "vi", não "resolvi". Quem clicar em "Ver pick" vai pra aba, que é onde a
 * decisão acontece.
 *
 * Mesma família visual do PlanUpsellToast e do PushPromptBanner · o site tem
 * um formato só de aviso. O que muda é a urgência: aqui não há atraso de
 * entrada (a odd vence em minutos, 1,4s de espera é 1,4s a menos) e o aviso
 * se retira sozinho, porque um pick que já venceu não deve continuar
 * chamando.
 */

/** Quanto tempo o aviso fica. A odd ao vivo dura minutos; o convite, menos. */
const TEMPO_EM_TELA = 25_000

/** Onde ele não entra · na própria aba o pick já aparece na lista. */
const FORA_DE = ['/checkout', '/login']

export default function LivePickToast() {
  const { livePickNovo, dismissLivePickNovo } = useNotifications()
  const { pathname, hash } = useLocation()
  const navigate = useNavigate()
  const [visivel, setVisivel] = useState(false)

  const naAbaAoVivo = pathname === '/picks' && hash === '#ao_vivo'
  const bloqueado = FORA_DE.some(r => pathname.startsWith(r)) || naAbaAoVivo

  useEffect(() => {
    if (!livePickNovo || bloqueado) { setVisivel(false); return }
    setVisivel(true)
    const t = setTimeout(() => { setVisivel(false); dismissLivePickNovo() }, TEMPO_EM_TELA)
    return () => clearTimeout(t)
  }, [livePickNovo?.id, bloqueado, dismissLivePickNovo])

  const fechar = () => { setVisivel(false); dismissLivePickNovo() }

  const abrir = () => {
    fechar()
    /* `navigate` e não <Link>: a aba é um hash da mesma rota, e o React Router
       não remonta a página quando só o hash muda · Picks.tsx lê o hash no
       mount. Navegar explicitamente garante que a aba troque mesmo se a pessoa
       já estiver em /picks noutra aba interna. */
    navigate(livePickNovo?.url || '/picks#ao_vivo')
  }

  return (
    <AnimatePresence>
      {visivel && livePickNovo && (
        <motion.div
          variants={toastUp}
          initial="hidden"
          animate="visible"
          exit="exit"
          /* Mesma faixa dos outros avisos (`bottom-24`), e não uma quarta: em
             `bottom-6` ele cairia por cima do banner de cookies. Quem cede o
             lugar é o convite de plano · ele se esconde enquanto este estiver
             na tela (ver PlanUpsellToast), porque oportunidade com prazo ganha
             de convite permanente. O `z` mais alto cobre o empate de um ciclo
             de render entre os dois. */
          className="fixed bottom-24 left-0 right-0 z-[9995] flex justify-center px-4 pointer-events-none"
        >
          <div className="pointer-events-auto w-full max-w-md bg-surface-1 border border-red-500/40 rounded-lg shadow-2xl px-4 py-4 flex items-center gap-3">
            <div className="w-9 h-9 rounded-full flex items-center justify-center shrink-0 bg-red-500/10">
              <Radio className="w-4 h-4 text-red-400" aria-hidden="true" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="flex items-center gap-1.5 text-sm font-black text-ink-1 leading-snug">
                <LiveDot tone="red" className="w-1.5 h-1.5 shrink-0" />
                <span className="truncate">{livePickNovo.title}</span>
              </p>
              {livePickNovo.body && (
                <p className="text-xs text-ink-3 leading-snug truncate">{livePickNovo.body}</p>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={abrir}
                className="px-3 py-1.5 rounded-lg text-xs font-black bg-red-500 hover:bg-red-400 text-white transition-colors"
              >
                Ver pick
              </button>
              <button
                onClick={fechar}
                aria-label="Dispensar aviso"
                className="w-7 h-7 flex items-center justify-center text-ink-3 hover:text-ink-1 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
