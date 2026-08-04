import { motion } from 'framer-motion'
import { Database, BrainCircuit, Percent, Target, Send } from 'lucide-react'
import { SectionHead } from '../components/ui'
import { fadeInUp, staggerContainer } from '../lib/motion'

/*
 * O caminho que um jogo percorre até virar pick.
 *
 * Linha do tempo vertical: no desktop os passos ficam lado a lado ligados por
 * um traço, no mobile viram uma coluna com o traço à esquerda. Mesma estrutura
 * nos dois, só muda a direção, então não existe uma segunda marcação escondida
 * por display:none.
 */

const STEPS = [
  {
    Icon: Database,
    title: 'Coleta de dados',
    desc: 'Forma recente, confronto direto, força de ataque e defesa, arbitragem e odds de mercado de cada jogo das ligas cobertas.',
  },
  {
    Icon: BrainCircuit,
    title: 'Análise da IA',
    desc: 'O motor estatístico cruza as variáveis e projeta o comportamento provável da partida em cada mercado.',
  },
  {
    Icon: Percent,
    title: 'Probabilidade',
    desc: 'A projeção vira probabilidade estimada, que é comparada com a probabilidade implícita na odd da casa.',
  },
  {
    Icon: Target,
    title: 'Value bet',
    desc: 'Só sobrevive o que tem valor esperado positivo: quando a nossa probabilidade é maior que a que o mercado está pagando.',
  },
  {
    Icon: Send,
    title: 'Pick publicada',
    desc: 'O que passou no corte é publicado com mercado, odd, confiança e a explicação do porquê. O resultado entra no histórico público.',
  },
]

export default function HowItWorks() {
  return (
    <section id="como-funciona" className="section section-alt">
      <div className="shell">
        <SectionHead
          eyebrow="Do dado à pick"
          title="Nada de achismo. Só dados reais e matemática."
          sub="Todo jogo passa pelo mesmo caminho, e o que não tem valor esperado positivo não vira pick."
        />

        <motion.ol
          variants={staggerContainer}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '0px 0px -80px 0px' }}
          className="relative grid gap-6 md:grid-cols-5 md:gap-4"
        >
          {/* Trilho. Vertical no mobile, horizontal a partir de md. */}
          <div
            aria-hidden="true"
            className="absolute left-[19px] top-2 bottom-2 w-px bg-line md:left-0 md:right-0 md:top-[19px] md:bottom-auto md:h-px md:w-auto"
          />

          {STEPS.map(({ Icon, title, desc }, i) => (
            <motion.li
              key={title}
              variants={fadeInUp}
              className="relative flex gap-4 md:flex-col md:gap-3"
            >
              <div className="relative z-10 w-10 h-10 rounded-lg bg-surface-0 border border-line-strong flex items-center justify-center shrink-0">
                <Icon className="w-4 h-4 text-accent" />
              </div>

              <div className="min-w-0 pb-2 md:pb-0">
                <div className="label-micro mb-1.5">Passo {i + 1}</div>
                <h3 className="font-display text-sm font-semibold text-ink-1 mb-1.5 leading-tight">
                  {title}
                </h3>
                <p className="text-xs text-ink-3 leading-relaxed">{desc}</p>
              </div>
            </motion.li>
          ))}
        </motion.ol>
      </div>
    </section>
  )
}
