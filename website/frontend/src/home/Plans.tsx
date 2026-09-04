import { motion } from 'framer-motion'
import { Check, X as XIcon } from 'lucide-react'

import { Badge, Button, SectionHead } from '../components/ui'
import { fmtPlanPrice, type Plan } from '../hooks/usePlans'
import { fadeInUp, staggerContainer } from '../lib/motion'
import { MODULOS_FREE, MODULOS_VIP } from '../lib/oferta'

/*
 * A tabela de planos da Home · fora do Home.tsx pelo mesmo motivo da seção de
 * resultados: ela vive lá embaixo, e o que ela importa (o catálogo da oferta,
 * os ícones da comparação) não tem por que viajar no chunk da primeira tela.
 */

/* ── Planos ─────────────────────────────────────────────────────────────── */

/*
 * A COMPARAÇÃO SAI DE lib/oferta, e não de uma lista escrita aqui.
 *
 * Esta era a TERCEIRA cópia do catálogo: a vitrine e o checkout já foram
 * unificados, e a tabela de planos da Home continuou à mão. Ela já estava
 * defasada · anunciava oito itens bloqueados no Free e nenhum deles era o Pick
 * Boost nem a estatística de jogador, os dois módulos mais recentes. Quem
 * compara plano numa tabela que esquece dois produtos decide com menos do que
 * existe.
 *
 * O Free lista o que ele tem E o que não tem, porque é assim que uma coluna de
 * comparação funciona: sem os itens em cinza, a pessoa não sabe o que está
 * deixando na mesa.
 */
const FREE_ITEMS: Array<[boolean, string]> = [
  ...MODULOS_FREE.map(m => [true, m.titulo] as [boolean, string]),
  ...MODULOS_VIP.map(m => [false, m.titulo] as [boolean, string]),
]

const TRIAL_ITEMS = [
  'Experimente tudo por 2 dias, sem pagar nada',
  'Vence sozinho, sem cobrança automática',
]

/* VIP é tudo: o que já vem no Free mais o que a assinatura abre. */
const VIP_ITEMS = [...MODULOS_FREE, ...MODULOS_VIP].map(m => m.titulo)

export default function Plans({ monthly }: { monthly: Plan }) {
  return (
    <section id="planos" className="section section-alt">
      <div className="shell">
        <SectionHead
          title="Comece de graça, assine se gostar"
          sub="2 dias com acesso VIP completo, sem precisar de cartão."
        />

        <motion.div
          variants={staggerContainer}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '0px 0px -80px 0px' }}
          className="grid md:grid-cols-3 gap-4 items-start"
        >
          {/* Free */}
          <motion.div variants={fadeInUp} className="bg-surface-0 border border-line rounded-lg p-6">
            <Badge tone="neutral">Free</Badge>
            <p className="font-mono text-3xl font-bold text-ink-1 mt-3 mb-0.5">R$ 0</p>
            <p className="text-ink-3 text-xs mb-6">Para sempre, sem cadastro de cartão</p>
            <ul className="space-y-2.5 mb-7">
              {FREE_ITEMS.map(([ok, t]) => (
                <li key={t} className="flex items-start gap-2.5">
                  {ok
                    ? <Check className="w-4 h-4 text-accent-ink shrink-0 mt-0.5" />
                    : <XIcon className="w-4 h-4 text-ink-4 shrink-0 mt-0.5" />}
                  <span className={`text-sm leading-snug ${ok ? 'text-ink-2' : 'text-ink-4'}`}>{t}</span>
                </li>
              ))}
            </ul>
            <Button to="/login?mode=register" variant="ghost" block>Criar conta grátis</Button>
          </motion.div>

          {/* VIP · destaque principal */}
          <motion.div variants={fadeInUp} className="relative bg-surface-0 border border-yellow-400/50 rounded-lg p-6 overflow-hidden">
            <div aria-hidden="true" className="absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-transparent via-yellow-400/80 to-transparent" />
            <div className="flex items-center justify-between gap-2 mb-3">
              <Badge tone="yellow">VIP</Badge>
              <Badge tone="yellow">Mais popular</Badge>
            </div>
            <p className="font-mono text-3xl font-bold text-ink-1 mb-0.5">
              {fmtPlanPrice(monthly.price)}<span className="text-base font-semibold text-ink-3">/mês</span>
            </p>
            <p className="text-ink-3 text-xs mb-6">
              Menos de {fmtPlanPrice(monthly.price / 30)} por dia. Pagamento único, sem renovação automática.
            </p>
            <ul className="space-y-2.5 mb-7">
              {VIP_ITEMS.map(t => (
                <li key={t} className="flex items-start gap-2.5">
                  <Check className="w-4 h-4 text-yellow-400 shrink-0 mt-0.5" />
                  <span className="text-sm text-ink-2 leading-snug">{t}</span>
                </li>
              ))}
            </ul>
            <Button to="/planos" variant="vip" block>Ver planos VIP</Button>
          </motion.div>

          {/* Teste grátis · gateway para o VIP */}
          <motion.div variants={fadeInUp} className="relative bg-surface-0 border border-accent/40 rounded-lg p-6 overflow-hidden">
            <div aria-hidden="true" className="absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-transparent via-accent/60 to-transparent" />
            <Badge tone="green">Teste gratuito</Badge>
            <p className="font-mono text-3xl font-bold text-ink-1 mt-3 mb-0.5">R$ 0</p>
            <p className="text-ink-2 text-xs mb-5">Acesso VIP completo por 2 dias</p>
            {/* O trial dá acesso ao mesmo conjunto do VIP -- por isso não lista
                item por item: repete o VIP ao lado e confunde quem compara. */}
            <div className="rounded-md bg-surface-1 border border-line px-4 py-3.5 mb-5 space-y-2">
              {TRIAL_ITEMS.map(t => (
                <p key={t} className="text-sm text-ink-2 leading-snug flex items-start gap-2">
                  <Check className="w-4 h-4 text-accent-ink shrink-0 mt-0.5" />
                  {t}
                </p>
              ))}
              <p className="text-xs text-ink-3 pt-1 border-t border-line mt-1">
                Tudo que está incluso no VIP, por 2 dias.
              </p>
            </div>
            <Button to="/login?mode=register" block>Ativar teste gratuito</Button>
          </motion.div>
        </motion.div>
      </div>
    </section>
  )
}
