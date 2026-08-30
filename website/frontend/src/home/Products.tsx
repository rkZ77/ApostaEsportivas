import { useCallback, useEffect, useState } from 'react'
import useEmblaCarousel from 'embla-carousel-react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { SectionHead, IconButton, Badge } from '../components/ui'
import { MODULOS } from '../lib/oferta'
import { cn } from '../lib/cn'

/*
 * Vitrine do que a plataforma entrega.
 *
 * A LISTA NÃO MORA MAIS AQUI. Ela era escrita à mão neste arquivo e de novo,
 * diferente, dentro do Checkout · a vitrine anunciava dez módulos e a tela de
 * pagar prometia seis frases genéricas que não citavam metade deles. As duas
 * leem de lib/oferta agora, que é também de onde sai a coluna VIP da página de
 * planos.
 *
 * Embla em vez de scroll-snap puro porque aqui o arraste com o mouse importa:
 * no desktop a maior parte do público não pensa em rolar uma faixa na
 * horizontal, e as setas mais o arraste resolvem isso. A rolagem nativa
 * continua funcionando por baixo, então sem JS a faixa ainda navega.
 */

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
          {MODULOS.map(({ Icon, titulo, desc, tag }) => (
            <article
              key={titulo}
              className={cn(
                'shrink-0 w-[248px] sm:w-[268px] p-5 rounded-lg select-none',
                'bg-surface-0 border border-line hover:border-line-strong',
                'transition-colors duration-2 ease-smooth',
              )}
            >
              <div className="flex items-start justify-between gap-2 mb-4">
                <div className="w-10 h-10 rounded-lg border border-line flex items-center justify-center">
                  <Icon className="w-4 h-4 text-accent-ink" />
                </div>
                {tag && <Badge tone={tag.tone}>{tag.label}</Badge>}
              </div>
              <h3 className="font-display text-sm font-semibold text-ink-1 mb-2">{titulo}</h3>
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
