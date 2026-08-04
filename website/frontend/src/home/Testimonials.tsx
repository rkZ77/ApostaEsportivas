import { motion } from 'framer-motion'
import { Quote } from 'lucide-react'
import { Badge, SectionHead } from '../components/ui'
import { fadeInUp, staggerContainer } from '../lib/motion'

/*
 * ┌────────────────────────────────────────────────────────────────────────┐
 * │ TODO · SUBSTITUIR POR DEPOIMENTOS REAIS ANTES DE DIVULGAR A HOME       │
 * │                                                                        │
 * │ Os textos abaixo são EXEMPLOS DE PREENCHIMENTO. Não são de usuários     │
 * │ reais e não podem ser apresentados como se fossem.                     │
 * │                                                                        │
 * │ Para publicar de verdade:                                              │
 * │   1. colher o depoimento com o usuário e pedir autorização de uso      │
 * │   2. trocar o conteúdo de TESTIMONIALS por esses depoimentos           │
 * │   3. apagar `isExample: true` de cada item                             │
 * │                                                                        │
 * │ Enquanto `isExample` for true, o card se anuncia como exemplo na tela. │
 * │ Isso é proposital: mesmo que a seção vá ao ar antes da troca, ela não  │
 * │ passa por prova social. Não remova o selo sem trocar o texto.          │
 * │                                                                        │
 * │ Para esconder a seção inteira até lá, basta esvaziar TESTIMONIALS: o   │
 * │ componente devolve null quando a lista está vazia.                     │
 * └────────────────────────────────────────────────────────────────────────┘
 */

interface Testimonial {
  quote: string
  name: string
  /** Contexto curto: tempo de uso, plano, cidade. */
  context: string
  /** true enquanto for texto de preenchimento. Ver o bloco acima. */
  isExample?: boolean
}

const TESTIMONIALS: Testimonial[] = [
  {
    quote: 'O que me segurou foi conseguir conferir o histórico inteiro sem precisar acreditar em ninguém. Cada pick que saiu está lá, com o resultado.',
    name: 'Nome do usuário',
    context: 'Plano VIP',
    isExample: true,
  },
  {
    quote: 'A parte de banca mudou mais o meu resultado que a pick em si. Passei a apostar a mesma unidade sempre em vez de dobrar quando dava errado.',
    name: 'Nome do usuário',
    context: 'Plano VIP',
    isExample: true,
  },
  {
    quote: 'Uso mais pela explicação do que pelo palpite. Ver por que a IA achou valor naquela linha me ensinou a olhar odd de um jeito diferente.',
    name: 'Nome do usuário',
    context: 'Plano Free',
    isExample: true,
  },
]

export default function Testimonials() {
  if (TESTIMONIALS.length === 0) return null

  const anyExample = TESTIMONIALS.some(t => t.isExample)

  return (
    <section className="section">
      <div className="shell">
        <SectionHead
          eyebrow="Quem usa"
          title="O que dizem sobre a plataforma"
          sub={anyExample
            ? 'Estamos coletando depoimentos de usuários. Os cards abaixo mostram o formato e serão trocados por relatos reais.'
            : undefined}
        />

        <motion.div
          variants={staggerContainer}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '0px 0px -80px 0px' }}
          className="grid gap-4 md:grid-cols-3"
        >
          {TESTIMONIALS.map((t, i) => (
            <motion.figure
              key={i}
              variants={fadeInUp}
              className="bg-surface-0 border border-line rounded-lg p-6 flex flex-col"
            >
              <Quote className="w-4 h-4 text-ink-4 mb-4 shrink-0" aria-hidden="true" />

              <blockquote className="text-sm text-ink-2 leading-relaxed flex-1">
                {t.quote}
              </blockquote>

              <figcaption className="mt-5 pt-4 border-t border-line flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-ink-1 truncate">{t.name}</p>
                  <p className="text-[11px] text-ink-4 truncate">{t.context}</p>
                </div>
                {t.isExample && <Badge tone="neutral">Exemplo</Badge>}
              </figcaption>
            </motion.figure>
          ))}
        </motion.div>
      </div>
    </section>
  )
}
