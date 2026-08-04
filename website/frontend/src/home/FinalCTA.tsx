import { motion } from 'framer-motion'
import { ArrowRight, Check } from 'lucide-react'
import { Button } from '../components/ui'

/*
 * Fechamento da Home.
 *
 * O bloco é delineado, não preenchido de verde: um painel gritante no fim da
 * página puxa o site pra estética de cassino, que é justamente o que o produto
 * não é. O acento fica só no brilho de fundo e no botão.
 */

const POINTS = [
  '2 dias de acesso VIP completo',
  'Sem cartão de crédito',
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
          {/* Luz difusa subindo do rodapé do bloco. Decorativa. */}
          <div
            aria-hidden="true"
            className="pointer-events-none absolute -bottom-24 left-1/2 -translate-x-1/2 w-[420px] h-[220px] bg-accent/15 blur-[90px] rounded-full"
          />
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 bg-data-grid bg-[length:28px_28px] opacity-40 [mask-image:radial-gradient(ellipse_70%_60%_at_50%_100%,black,transparent)]"
          />

          <div className="relative">
            <h2 className="font-display text-2xl sm:text-3xl font-bold text-ink-1 leading-tight mb-3">
              Comece hoje com os picks de hoje.
            </h2>
            <p className="text-ink-2 text-sm leading-relaxed max-w-md mx-auto mb-8">
              Cria a conta, ativa o teste e vê as análises da IA para os jogos de agora.
              Se não gostar, o histórico completo continua público de qualquer jeito.
            </p>

            <div className="flex flex-col sm:flex-row items-center justify-center gap-3 mb-8">
              <Button to="/login?mode=register" size="lg" IconRight={ArrowRight}>
                Criar conta grátis
              </Button>
              <Button to="/resultados" variant="ghost" size="lg">
                Ver resultados antes
              </Button>
            </div>

            <ul className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2">
              {POINTS.map(p => (
                <li key={p} className="flex items-center gap-1.5 text-xs text-ink-3">
                  <Check className="w-3.5 h-3.5 text-accent shrink-0" />
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
