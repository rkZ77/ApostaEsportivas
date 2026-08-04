import { useCallback, useEffect, useState } from 'react'
import useEmblaCarousel from 'embla-carousel-react'
import {
  ChevronLeft, ChevronRight, Crown, Gift, Layers, Rocket,
  Wallet, BarChart3, Bot, CalendarDays, ShieldHalf, Flag,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { SectionHead, IconButton, Badge } from '../components/ui'
import { cn } from '../lib/cn'

/*
 * Vitrine do que a plataforma entrega.
 *
 * Embla em vez de scroll-snap puro porque aqui o arraste com o mouse importa:
 * no desktop a maior parte do público não pensa em rolar uma faixa na
 * horizontal, e as setas mais o arraste resolvem isso. A rolagem nativa
 * continua funcionando por baixo, então sem JS a faixa ainda navega.
 */

interface Product {
  Icon: LucideIcon
  title: string
  desc: string
  tag?: { label: string; tone: 'yellow' | 'green' | 'blue' | 'orange' | 'purple' | 'sky' }
}

const PRODUCTS: Product[] = [
  {
    Icon: Crown,
    title: 'Picks VIP',
    desc: 'Os picks de maior confiança do dia, com mercado, odd, stake sugerida e a análise que sustenta cada um.',
    tag: { label: 'VIP', tone: 'yellow' },
  },
  {
    Icon: Gift,
    title: 'Dica do dia',
    desc: 'Um pick gratuito por dia, aberto para qualquer conta. Serve para conferir o método antes de assinar.',
    tag: { label: 'Free', tone: 'green' },
  },
  {
    Icon: Layers,
    title: 'Múltiplas',
    desc: 'Combinações montadas pela IA só quando todas as seleções passam no critério estatístico.',
    tag: { label: 'VIP', tone: 'blue' },
  },
  {
    Icon: Rocket,
    title: 'Alavancagem',
    desc: 'Sequência de odds curtas com reinvestimento do lucro, para crescimento de banca com risco controlado.',
    tag: { label: 'VIP', tone: 'orange' },
  },
  {
    Icon: Flag,
    title: 'Mercado de faltas',
    desc: 'Modelo próprio para linhas de faltas, um mercado que a maioria das casas precifica com folga.',
    tag: { label: 'VIP', tone: 'purple' },
  },
  {
    Icon: ShieldHalf,
    title: 'Defesas de goleiro',
    desc: 'Projeção de defesas por goleiro a partir do volume de finalização esperado dos dois lados.',
    tag: { label: 'VIP', tone: 'sky' },
  },
  {
    Icon: Wallet,
    title: 'Gestão de banca',
    desc: 'Stake sugerida por Kelly, controle de unidade, histórico de saques e fechamento mensal automático.',
  },
  {
    Icon: BarChart3,
    title: 'Resultados auditáveis',
    desc: 'Todo pick publicado entra no histórico público, com win rate por liga, por jogo e por mês.',
  },
  {
    Icon: Bot,
    title: 'Agente de futebol',
    desc: 'Uma IA que responde sobre qualquer jogo, mercado ou estratégia usando os dados reais do sistema.',
    tag: { label: 'VIP', tone: 'green' },
  },
  {
    Icon: CalendarDays,
    title: 'Agenda de jogos',
    desc: 'Todos os jogos das ligas cobertas, marcando quais já foram analisados e quais têm pick.',
  },
]

export default function Products() {
  const [emblaRef, embla] = useEmblaCarousel({
    align: 'start',
    containScroll: 'trimSnaps',
    dragFree: true,
  })
  const [canPrev, setCanPrev] = useState(false)
  const [canNext, setCanNext] = useState(false)

  const sync = useCallback(() => {
    if (!embla) return
    setCanPrev(embla.canScrollPrev())
    setCanNext(embla.canScrollNext())
  }, [embla])

  useEffect(() => {
    if (!embla) return
    sync()
    embla.on('select', sync).on('reInit', sync)
    return () => { embla.off('select', sync).off('reInit', sync) }
  }, [embla, sync])

  return (
    <section id="produtos" className="section">
      <div className="shell">
        <div className="flex items-end justify-between gap-4 mb-8">
          <SectionHead
            eyebrow="O que você recebe"
            title="Uma plataforma, vários tipos de análise"
            sub="Cada módulo tem o seu próprio modelo. Nenhum deles publica sem passar no corte de valor."
            className="text-left mb-0 [&_p]:mx-0"
          />

          <div className="hidden md:flex items-center gap-2 shrink-0 pb-1">
            <IconButton
              Icon={ChevronLeft}
              label="Produtos anteriores"
              disabled={!canPrev}
              onClick={() => embla?.scrollPrev()}
            />
            <IconButton
              Icon={ChevronRight}
              label="Próximos produtos"
              disabled={!canNext}
              onClick={() => embla?.scrollNext()}
            />
          </div>
        </div>
      </div>

      {/* Sangra pra fora do shell de propósito: o card cortado na borda é o que
          sinaliza que a faixa continua. Dentro do container ela pareceria uma
          grade que simplesmente acabou. */}
      <div className="overflow-hidden" ref={emblaRef}>
        <div className="flex gap-4 px-4 md:px-[max(1rem,calc((100vw-64rem)/2))]">
          {PRODUCTS.map(({ Icon, title, desc, tag }) => (
            <article
              key={title}
              className={cn(
                'shrink-0 w-[248px] sm:w-[268px] p-5 rounded-lg select-none',
                'bg-surface-0 border border-line hover:border-line-strong',
                'transition-colors duration-2 ease-smooth',
              )}
            >
              <div className="flex items-start justify-between gap-2 mb-4">
                <div className="w-10 h-10 rounded-lg border border-line flex items-center justify-center">
                  <Icon className="w-4 h-4 text-accent" />
                </div>
                {tag && <Badge tone={tag.tone}>{tag.label}</Badge>}
              </div>
              <h3 className="font-display text-sm font-semibold text-ink-1 mb-2">{title}</h3>
              <p className="text-xs text-ink-3 leading-relaxed">{desc}</p>
            </article>
          ))}
        </div>
      </div>

      <div className="shell mt-4 md:hidden">
        <p className="text-[11px] text-ink-4 text-center">Arraste para ver todos</p>
      </div>
    </section>
  )
}
