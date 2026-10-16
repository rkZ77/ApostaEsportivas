import { m as motion } from 'framer-motion'
import { Check } from 'lucide-react'
import { Button } from '../components/ui'
import LinhasDeCampo from '../components/ui/LinhasDeCampo'

/*
 * Fechamento da Home.
 *
 * O bloco é delineado, não preenchido de verde: um painel gritante no fim da
 * página puxa o site pra estética de cassino, que é justamente o que o produto
 * não é. O acento fica só nas linhas de campo do fundo e no botão.
 */

const POINTS = [
  '2 dias com o Pick IA Pro aberto',
  'Cancele quando quiser',
]

export default function FinalCTA() {
  return (
    <section className="section">
      <div className="shell">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '0px 0px -80px 0px' }}
          transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
          className="relative overflow-hidden rounded-lg border border-line bg-surface-0 px-6 py-12 sm:px-12 sm:py-16 text-center"
        >
          {/* Linhas de campo subindo da base do bloco, no lugar da luz verde
              difusa e da grade (15/10/2026) · ver ui/LinhasDeCampo. */}
          <LinhasDeCampo foco="base" />

          <div className="relative">
            <h2 className="font-display text-2xl sm:text-3xl font-bold text-ink-1 leading-tight mb-3">
              Comece hoje com os picks de hoje.
            </h2>
            <p className="text-ink-2 text-sm leading-relaxed max-w-md mx-auto mb-8">
              Cria a conta, ativa o teste e vê as análises da IA para os jogos de agora.
              Se não gostar, o histórico completo continua público de qualquer jeito.
            </p>

            <div className="flex flex-col sm:flex-row items-center justify-center gap-3 mb-8">
              <Button to="/login?mode=register" size="lg">
                Criar conta grátis
              </Button>
              <Button to="/resultados" variant="ghost" size="lg">
                Ver resultados antes
              </Button>
            </div>

            <ul className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2">
              {POINTS.map(p => (
                <li key={p} className="flex items-center gap-1.5 text-xs text-ink-3">
                  <Check className="w-3.5 h-3.5 text-accent-ink shrink-0" />
                  {p}
                </li>
              ))}
            </ul>
          </div>
        </motion.div>
      </div>
    </section>
  )
}
