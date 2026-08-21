import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Mail, X } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { useOnboarding } from '../context/OnboardingContext'
import api from '../services/api'
import { toastUp } from '../lib/motion'

/*
 * Convite pra confirmar o e-mail · vale 2 dias de VIP.
 *
 * Existe porque o trial deixou de sair no cadastro quando o CPF foi removido
 * (18/08/2026). Antes a pessoa entrava já como trial e não precisava saber de
 * nada; agora ela entra como free e o VIP só chega depois do clique no link.
 * O único aviso existente era um ponto amarelo no avatar do Navbar, que não
 * comunica recompensa nenhuma · sem isto aqui, a troca reduziria a fricção do
 * cadastro e mataria o trial no mesmo movimento.
 *
 * Não é dispensável pra sempre de propósito: volta a cada RESNOOZE_DAYS
 * enquanto houver trial na mesa, mesma régua do PushPromptBanner.
 */

const LS_KEY = 'pickia_verify_email_dismissed_at'
const RESNOOZE_DAYS = 3

function isSnoozed(): boolean {
  const raw = localStorage.getItem(LS_KEY)
  if (!raw) return false
  const dismissedAt = Number(raw)
  if (!dismissedAt) return false
  return (Date.now() - dismissedAt) / (1000 * 60 * 60 * 24) < RESNOOZE_DAYS
}

export default function VerifyEmailBanner() {
  const { user } = useAuth()
  /*
   * Espera o tour de boas-vindas sair da frente.
   *
   * Este aviso é `z-[9990]` e o tour é `z-[80]`, então ele pulava na frente do
   * tutorial no primeiro acesso · que é exatamente o momento em que os dois
   * disputam. E não some a mensagem: enquanto o tour está aberto, quem convida
   * a confirmar o e-mail é o passo "Confirme seu e-mail e ganhe 2 dias de VIP",
   * com o mesmo botão de reenviar. Fechado o tour, este aviso volta ao normal.
   */
  const { aberto: tourAberto, pendente: tourPendente, carregado: tourCarregado } = useOnboarding()
  const tourNaFrente = tourAberto || !tourCarregado || tourPendente
  const [visible, setVisible] = useState(false)
  const [sending, setSending] = useState(false)
  const [sent, setSent]       = useState(false)

  // `trial_used` não vem no payload do login, só no /auth/me. Enquanto ele for
  // undefined tratamos como "ainda tem trial", que é o caso de quem acabou de
  // se cadastrar · o custo de errar pra esse lado é um convite a mais, e pra
  // outro é o usuário nunca descobrir que tem VIP esperando.
  const trialNaMesa = user?.trial_used !== true

  useEffect(() => {
    if (!user) { setVisible(false); return }
    if (user.email_verified !== false) { setVisible(false); return }
    if (!trialNaMesa) { setVisible(false); return }
    if (tourNaFrente) { setVisible(false); return }
    if (isSnoozed()) return
    const t = setTimeout(() => setVisible(true), 1200)
    return () => clearTimeout(t)
  }, [user?.id, user?.email_verified, trialNaMesa, tourNaFrente])

  const reenviar = async () => {
    setSending(true)
    try {
      await api.post('/auth/resend-verification')
      setSent(true)
    } catch {
      /* silencioso: o usuário já tem o e-mail original na caixa */
    } finally {
      setSending(false)
    }
  }

  const dispensar = () => {
    localStorage.setItem(LS_KEY, String(Date.now()))
    setVisible(false)
  }

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          variants={toastUp}
          initial="hidden"
          animate="visible"
          exit="exit"
          className="fixed bottom-24 left-0 right-0 z-[9990] flex justify-center px-4 pointer-events-none"
        >
          <div className="pointer-events-auto w-full max-w-sm bg-surface-1 border border-line-strong rounded-lg shadow-2xl px-4 py-4 flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-green-500/10 flex items-center justify-center shrink-0">
              <Mail className="w-4 h-4 text-green-400" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-black text-ink-1 leading-snug">2 dias de VIP esperando</p>
              <p className="text-xs text-ink-3 leading-snug">
                {sent ? 'E-mail reenviado. Confira sua caixa.' : 'Confirme seu e-mail para liberar'}
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {!sent && (
                <motion.button
                  whileTap={{ scale: 0.95 }}
                  onClick={reenviar}
                  disabled={sending}
                  className="px-3 py-1.5 rounded-lg bg-green-500 hover:bg-green-400 text-black text-xs font-black transition-colors disabled:opacity-50"
                >
                  {sending ? '...' : 'Reenviar'}
                </motion.button>
              )}
              <button
                onClick={dispensar}
                aria-label="Fechar aviso"
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
