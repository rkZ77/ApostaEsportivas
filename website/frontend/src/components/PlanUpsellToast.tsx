import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Crown, X } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { useOnboarding } from '../context/OnboardingContext'
import { toastUp } from '../lib/motion'
import { adiarPlano, convitePlano, planoAdiado } from '../lib/planoUpsell'

/*
 * Convite de plano · aviso no rodapé.
 *
 * Era uma faixa larga no topo, dentro do PageShell (PlanUpsellBar, removida em
 * 21/08 a pedido do usuário). Ela custava uma linha inteira do topo em TODA
 * tela do app e empurrava para baixo justamente o conteúdo que a pessoa abriu a
 * página para ver. No rodapé ela continua à vista, sem mexer no layout.
 *
 * Mesma família visual do VerifyEmailBanner e do PushPromptBanner: card
 * flutuante, `toastUp`, largura de coluna única. O site passa a ter um formato
 * só de aviso em vez de dois.
 *
 * Dispensar continua valendo 24h, e agora não some de vez: o mesmo convite fica
 * na Central de Notificações enquanto o estado da conta não mudar (ver
 * ID_NOTIFICACAO_PLANO em lib/planoUpsell).
 */

/** Onde ele não entra. Quem já está no checkout não precisa ser convidado. */
const FORA_DE = ['/checkout', '/planos']

export default function PlanUpsellToast() {
  const { user, isAdmin, daysUntilExpiry } = useAuth()
  const { pathname } = useLocation()
  /* O tour é `z-[80]` e este aviso é `z-[9990]`. Sem esperar, ele pularia na
     frente do tutorial no primeiro acesso · e vender assinatura para quem ainda
     não viu o produto funcionar é o pior momento possível. */
  const { aberto: tourAberto, pendente: tourPendente, carregado: tourCarregado } = useOnboarding()
  const tourNaFrente = tourAberto || !tourCarregado || tourPendente

  const [visivel, setVisivel] = useState(false)
  const convite = convitePlano(user, daysUntilExpiry, isAdmin)
  const bloqueado = FORA_DE.some(r => pathname.startsWith(r))

  useEffect(() => {
    if (!convite || bloqueado || tourNaFrente || planoAdiado()) {
      setVisivel(false)
      return
    }
    /* O atraso não é enfeite: entrar junto com a página faz o aviso aparecer
       antes de a pessoa ter olhado o conteúdo, e é lido como pop-up. */
    const t = setTimeout(() => setVisivel(true), 1400)
    return () => clearTimeout(t)
  }, [convite?.titulo, bloqueado, tourNaFrente])

  const dispensar = () => {
    adiarPlano()
    setVisivel(false)
  }

  const cor = convite?.tone === 'amber'
    ? { icone: 'text-amber-400', bolha: 'bg-amber-400/10', botao: 'bg-amber-400 hover:bg-amber-300 text-on-fill' }
    : { icone: 'text-yellow-400', bolha: 'bg-yellow-400/10', botao: 'bg-yellow-400 hover:bg-yellow-300 text-on-fill' }

  return (
    <AnimatePresence>
      {visivel && convite && (
        <motion.div
          variants={toastUp}
          initial="hidden"
          animate="visible"
          exit="exit"
          /* Mesma faixa vertical do VerifyEmailBanner, e nunca os dois ao mesmo
             tempo: `convitePlano` devolve null para quem ainda pode ganhar o
             trial confirmando o e-mail, que é exatamente quem vê o outro. */
          className="fixed bottom-24 left-0 right-0 z-[9990] flex justify-center px-4 pointer-events-none"
        >
          {/* `max-w-md` e não `sm` como os vizinhos: este aviso tem título E corpo
                com conteúdo variável (o prazo do trial entra no título), e em 384px
                os dois quebravam em quatro linhas dentro de um card de 72px. */}
          <div className="pointer-events-auto w-full max-w-md bg-surface-1 border border-line-strong rounded-lg shadow-2xl px-4 py-4 flex items-center gap-3">
            <div className={`w-9 h-9 rounded-full flex items-center justify-center shrink-0 ${cor.bolha}`}>
              <Crown className={`w-4 h-4 ${cor.icone}`} aria-hidden="true" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-black text-ink-1 leading-snug">{convite.titulo}</p>
              <p className="text-xs text-ink-3 leading-snug">{convite.texto}</p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <Link
                to={convite.to}
                onClick={() => setVisivel(false)}
                className={`px-3 py-1.5 rounded-lg text-xs font-black transition-colors ${cor.botao}`}
              >
                {convite.cta}
              </Link>
              <button
                onClick={dispensar}
                aria-label="Dispensar por hoje"
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
