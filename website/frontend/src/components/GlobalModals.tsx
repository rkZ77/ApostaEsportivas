import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'

import { useAuth } from '../context/AuthContext'
import { useNotifications } from '../context/NotificationContext'
import MonthlyCloseModal from './MonthlyCloseModal'
import TrialEndedModal from './TrialEndedModal'

/*
 * Modais que vivem fora do <Routes>.
 *
 * Saiu de App.tsx em 14/08 pra virar chunk próprio. Junto com o modal vinha o
 * framer-motion inteiro (43,8 KB comprimidos, medidos no build), e ele estava
 * no caminho crítico de TODA página · inclusive Termos, Privacidade e o link
 * público de pick compartilhado, que não animam nada. Era cerca de um quarto do
 * JavaScript da Home baixado e executado antes do primeiro pixel, para um popup
 * que aparece uma vez por mês, para quem está logado.
 */

// Rotas onde o fechamento pode pular na frente do usuário. Lista de permissão,
// não de bloqueio: GlobalModals vive fora do <Routes>, então sem isso o popup
// aparece em TUDO · landing, blog, termos, link público de pick compartilhado.
// Quem está logado e cai na home (admin não é redirecionado pra /picks) levava
// o modal por cima da página de vendas. /checkout fica de fora de propósito:
// não se interrompe um pagamento em andamento.
const MONTHLY_CLOSE_ROUTES = [
  '/picks', '/banca', '/meus-picks', '/fixtures', '/estatisticas', '/agente', '/profile', '/admin',
]

export default function GlobalModals() {
  const { user, isAdmin } = useAuth()
  const { pathname } = useLocation()
  // ?preview=monthly renderiza o modal com dados FABRICADOS (ferramenta de
  // ajuste visual). Restrito a admin: qualquer usuário logado conseguia abrir
  // e printar um fechamento de +R$ 187,50 que nunca existiu.
  const isPreview = isAdmin && new URLSearchParams(window.location.search).get('preview') === 'monthly'
  const { pendingMonthlyClose, monthlyCloseOpen, openMonthlyClose, closeMonthlyClose,
          pendingTrialEnded, markRead } = useNotifications()
  const [trialEndedOpen, setTrialEndedOpen] = useState(false)
  const [trialEndedVisto, setTrialEndedVisto] = useState(false)

  const inAppRoute = MONTHLY_CLOSE_ROUTES.some(r => pathname === r || pathname.startsWith(`${r}/`))

  // Abre sozinho no primeiro acesso depois da virada do mês. O gatilho é a
  // notificação do servidor ainda não lida, então isso vale por conta (não por
  // navegador) e fechar o popup não apaga mais o fechamento: ele continua no
  // sino até a banca ser confirmada.
  useEffect(() => {
    if (!user) return
    if (isPreview || (pendingMonthlyClose && inAppRoute)) openMonthlyClose()
  }, [user?.id, pendingMonthlyClose?.id, inAppRoute, isPreview, openMonthlyClose])

  /*
   * Fim do teste grátis · abre uma vez e nunca mais.
   *
   * `trialEndedVisto` é só a trava DESTA sessão de página, pra o modal não
   * reabrir enquanto o markRead não volta do servidor (o poll de 60s traria a
   * notificação ainda como não lida nesse intervalo). A garantia de verdade é
   * do servidor: dedupe_key fixa + UNIQUE (user_id, dedupe_key), e o
   * rebaixamento de trial pra free só acontece uma vez na vida da conta.
   *
   * Não concorre com o fechamento mensal: dois modais na mesma tela é um em
   * cima do outro. O fechamento tem prioridade por ser o que pede AÇÃO (a
   * pessoa confirma a banca do mês); este aqui é convite, e espera a vez.
   */
  const podeAbrirTrial = pendingTrialEnded && inAppRoute && !monthlyCloseOpen && !pendingMonthlyClose

  useEffect(() => {
    if (!user || trialEndedVisto) return
    if (podeAbrirTrial) setTrialEndedOpen(true)
  }, [user?.id, podeAbrirTrial, trialEndedVisto])

  const fecharTrialEnded = () => {
    setTrialEndedOpen(false)
    setTrialEndedVisto(true)
    if (pendingTrialEnded) markRead(pendingTrialEnded.id)
  }

  return (
    <AnimatePresence>
      {monthlyCloseOpen && <MonthlyCloseModal onClose={closeMonthlyClose} />}
      {trialEndedOpen && !monthlyCloseOpen && <TrialEndedModal onClose={fecharTrialEnded} />}
    </AnimatePresence>
  )
}
