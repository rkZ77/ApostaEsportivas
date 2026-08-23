import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Lock, Sparkles, X } from 'lucide-react'
import { backdropFade, sheetUp } from '../lib/motion'

/*
 * Fim do acesso · o único popup de conversão do site.
 *
 * POR QUE INTERROMPE, se a regra da casa é o sino
 * -----------------------------------------------
 * O changelog em modal foi removido em 2026-08-05 justamente por interromper
 * quem abriu o site pra ver picks (ver UpdateBanner.tsx). Este é outro caso, e
 * a diferença é o momento: a pessoa acabou de PERDER acesso. Ela vai bater no
 * cadeado de qualquer jeito nos próximos cliques · avisar antes é menos
 * interrupção que deixar descobrir errando. É o mesmo critério que manteve o
 * popup do fechamento mensal de pé: momento de decisão, não recado.
 *
 * DOIS FINAIS, UM COMPONENTE
 * --------------------------
 * Nasceu só pro teste grátis (era TrialEndedModal). O VIP vencido ganhou a
 * mesma tela em 23/08/2026, e não uma cópia: o esqueleto é idêntico e o que
 * muda é o verbo · quem testou ASSINA, quem assinou RENOVA. Duas versões desse
 * arquivo só garantiriam que uma envelhecesse, e a que envelheceria seria a do
 * VIP, que aparece menos.
 *
 * UMA VEZ SÓ, POR CONTA (não por navegador)
 * -----------------------------------------
 * O gatilho é a notificação `trial_ended` / `vip_ended` ainda não lida. Fechar
 * aqui marca como lida, e a notificação tem `dedupe_key` em cima de um UNIQUE
 * (user_id, dedupe_key). No teste a chave é fixa · não existe segunda linha pra
 * criar, e acima disso o rebaixamento de trial pra free só acontece uma vez na
 * vida da conta (`trial_used = TRUE`, nunca reativado). No VIP a chave carrega
 * a data do vencimento, então cada ciclo de assinatura avisa uma vez · é o
 * comportamento certo: quem assinou de novo e deixou vencer de novo perdeu o
 * acesso de novo.
 *
 * Fechar não perde nada: o item continua no sino, com o mesmo link.
 */

export type FimDeAcesso = 'trial' | 'vip'

/** O que a pessoa tinha até ontem · a lista é o argumento, e é a mesma nos
    dois casos porque o acesso perdido é o mesmo. */
const PERDIDOS = [
  'Picks VIP do dia',
  'Múltiplas e alavancagem',
  'Mercados de faltas e defesas',
  'Agente de futebol com IA',
]

const COPY: Record<FimDeAcesso, {
  rotulo: string; titulo: string; intro: string; cta: string
}> = {
  trial: {
    rotulo: 'Teste grátis',
    titulo: 'Seus 2 dias acabaram',
    intro: 'Sua conta voltou pro plano free. O que estava liberado até agora:',
    cta: 'Assinar o VIP',
  },
  vip: {
    rotulo: 'Assinatura VIP',
    titulo: 'Seu VIP acabou',
    intro: 'Sua assinatura venceu e a conta voltou pro plano free. O que sai do ar:',
    cta: 'Renovar o VIP',
  },
}

export default function AccessEndedModal(
  { tipo, onClose }: { tipo: FimDeAcesso; onClose: () => void },
) {
  const navigate = useNavigate()
  const copy = COPY[tipo]

  const assinar = () => {
    onClose()
    navigate('/checkout')
  }

  return (
    <motion.div
      variants={backdropFade} initial="hidden" animate="visible" exit="exit"
      className="fixed inset-0 bg-black/90 backdrop-blur-sm z-[9998] flex items-end sm:items-center justify-center"
    >
      <motion.div
        variants={sheetUp}
        className="bg-surface-0 border border-line rounded-t-2xl sm:rounded-lg w-full sm:max-w-sm shadow-2xl overflow-y-auto max-h-[92dvh]"
      >
        <div className="px-5 pt-5 pb-2 flex items-start justify-between gap-3">
          <div>
            <p className="text-[10px] font-black text-ink-3 mb-0.5">{copy.rotulo}</p>
            <h2 className="text-ink-1 font-bold text-xl">{copy.titulo}</h2>
          </div>
          <button
            onClick={onClose}
            aria-label="Fechar"
            className="w-8 h-8 flex items-center justify-center rounded-full border border-line text-ink-3 hover:text-ink-1 transition-colors shrink-0"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 pb-5">
          <p className="text-sm text-ink-2 leading-relaxed mb-4">{copy.intro}</p>

          <ul className="space-y-2 mb-5">
            {PERDIDOS.map(item => (
              <li key={item} className="flex items-center gap-2.5">
                <Lock className="w-3.5 h-3.5 text-ink-4 shrink-0" />
                <span className="text-sm text-ink-3 line-through decoration-ink-4/60">{item}</span>
              </li>
            ))}
          </ul>

          <motion.button
            whileTap={{ scale: 0.98 }}
            onClick={assinar}
            className="w-full py-3 rounded-lg bg-green-600 hover:bg-green-500 text-ink-1 text-sm font-black transition-colors flex items-center justify-center gap-2"
          >
            <Sparkles className="w-4 h-4" />
            {copy.cta}
          </motion.button>

          {/* A saída fica explícita e sem peso. Popup de conversão sem porta de
              saída visível é o que faz a pessoa fechar a aba em vez do modal. */}
          <button
            onClick={onClose}
            className="w-full py-2.5 mt-2 text-xs font-semibold text-ink-4 hover:text-ink-2 transition-colors"
          >
            Continuar no free
          </button>

          <p className="text-[11px] text-ink-4 leading-relaxed mt-3 text-center">
            A dica do dia continua liberada pra você, todo dia.
          </p>
        </div>
      </motion.div>
    </motion.div>
  )
}
