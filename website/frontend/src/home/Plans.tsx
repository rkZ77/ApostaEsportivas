import { motion } from 'framer-motion'
import { Check, X as XIcon } from 'lucide-react'

import { Badge, Button, SectionHead } from '../components/ui'
import { fmtPlanPrice, type Plan } from '../hooks/usePlans'
import { fadeInUp, staggerContainer } from '../lib/motion'
import { MODULOS_FREE, MODULOS_PAGOS, MODULOS_PRO } from '../lib/oferta'

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
  ...MODULOS_PAGOS.map(m => [false, m.titulo] as [boolean, string]),
  ...MODULOS_PRO.map(m => [false, m.titulo] as [boolean, string]),
]

/*
 * O Pick IA é tudo do Free mais o pré-jogo. Os dois módulos do Pro entram
 * NEGADOS aqui pelo mesmo motivo da coluna Free: a diferença entre os dois
 * planos pagos é o que a pessoa está decidindo nesta tela, e uma lista que
 * só mostra o que tem esconde justamente a decisão.
 */
const BASE_ITEMS: Array<[boolean, string]> = [
  ...MODULOS_FREE.map(m => [true, m.titulo] as [boolean, string]),
  ...MODULOS_PAGOS.map(m => [true, m.titulo] as [boolean, string]),
  ...MODULOS_PRO.map(m => [false, m.titulo] as [boolean, string]),
]

/* O Pro é tudo. */
const PRO_ITEMS = [...MODULOS_FREE, ...MODULOS_PAGOS, ...MODULOS_PRO].map(m => m.titulo)

export default function Plans({ monthly, monthlyBase }: { monthly: Plan; monthlyBase: Plan }) {
  return (
    <section id="planos" className="section section-alt">
      <div className="shell">
        <SectionHead
          title="Comece de graça, assine se gostar"
          sub="2 dias com o Pick IA Pro aberto, sem precisar de cartão."
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

          {/* Pick IA · a entrada paga */}
          <motion.div variants={fadeInUp} className="bg-surface-0 border border-line rounded-lg p-6">
            <Badge tone="neutral">Pick IA</Badge>
            <p className="font-mono text-3xl font-bold text-ink-1 mt-3 mb-0.5">
              {fmtPlanPrice(monthlyBase.price)}<span className="text-base font-semibold text-ink-3">/mês</span>
            </p>
            <p className="text-ink-3 text-xs mb-6">
              Todos os picks de pré-jogo. Pagamento único, sem renovação automática.
            </p>
            <ul className="space-y-2.5 mb-7">
              {BASE_ITEMS.map(([ok, t]) => (
                <li key={t} className="flex items-start gap-2.5">
                  {ok
                    ? <Check className="w-4 h-4 text-accent-ink shrink-0 mt-0.5" />
                    : <XIcon className="w-4 h-4 text-ink-4 shrink-0 mt-0.5" />}
                  <span className={`text-sm leading-snug ${ok ? 'text-ink-2' : 'text-ink-4'}`}>{t}</span>
                </li>
              ))}
            </ul>
            <Button to="/planos" variant="ghost" block>Ver o Pick IA</Button>
          </motion.div>

          {/* Pick IA Pro · destaque principal */}
          <motion.div variants={fadeInUp} className="relative bg-surface-0 border border-yellow-400/50 rounded-lg p-6 overflow-hidden">
            <div aria-hidden="true" className="absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-transparent via-yellow-400/80 to-transparent" />
            <div className="flex items-center justify-between gap-2 mb-3">
              <Badge tone="yellow">Pick IA Pro</Badge>
              <Badge tone="yellow">Mais popular</Badge>
            </div>
            <p className="font-mono text-3xl font-bold text-ink-1 mb-0.5">
              {fmtPlanPrice(monthly.price)}<span className="text-base font-semibold text-ink-3">/mês</span>
            </p>
            <p className="text-ink-3 text-xs mb-6">
              Menos de {fmtPlanPrice(monthly.price / 30)} por dia. Pagamento único, sem renovação automática.
            </p>
            <ul className="space-y-2.5 mb-5">
              {PRO_ITEMS.map(t => (
                <li key={t} className="flex items-start gap-2.5">
                  <Check className="w-4 h-4 text-yellow-400 shrink-0 mt-0.5" />
                  <span className="text-sm text-ink-2 leading-snug">{t}</span>
                </li>
              ))}
            </ul>
            {/* O teste grátis era uma quarta coluna, e uma coluna de R$ 0 ao
                lado de outra de R$ 0 (o Free) fazia a grade parecer ter dois
                planos gratuitos. Ele é o caminho de entrada DESTE plano: o
                trial abre o Pro por 2 dias, então mora aqui. */}
            <div className="rounded-md bg-surface-1 border border-line px-4 py-3 mb-5">
              <p className="text-sm text-ink-2 leading-snug flex items-start gap-2">
                <Check className="w-4 h-4 text-accent-ink shrink-0 mt-0.5" />
                2 dias grátis com tudo isto aberto, sem pedir cartão.
              </p>
            </div>
            <Button to="/planos" variant="vip" block>Ver o Pick IA Pro</Button>
          </motion.div>
        </motion.div>
      </div>
    </section>
  )
}
