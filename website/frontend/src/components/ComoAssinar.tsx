import { useEffect, useState } from 'react'
import {
  Crown, CreditCard, Target, Plus, X, RefreshCw, Wallet, BarChart3,
  Radio, TrendingUp, Headphones,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { WA_SUPPORT } from '../lib/support'
import { SEM_RENOVACAO_AUTOMATICA } from '../lib/oferta'
import { cn } from '../lib/cn'

/*
 * "COMO FUNCIONA" EM TRÊS PASSOS + FAQ DA ASSINATURA (2026-09-25).
 *
 * Os dois blocos vieram da página de produto da KaySto: passos numerados
 * ligados por uma linha, e perguntas em sanfona com ícone. Aqui eles
 * substituem o card "Como funciona o pagamento", que dizia a mesma coisa em
 * duas linhas soltas · e respondem as objeções que decidem a compra antes do
 * checkout, não depois.
 *
 * Nada de promessa que o produto não cumpre: sem "lucro garantido", e o que
 * vale pra cobrança sai de lib/oferta, a mesma frase do checkout.
 */

const PASSOS: Array<{ Icon: LucideIcon; titulo: string; desc: string }> = [
  { Icon: Crown,      titulo: 'Escolha o plano',   desc: 'Pick IA ou Pick IA Pro, no período que fizer sentido pra você.' },
  { Icon: CreditCard, titulo: 'Pague do seu jeito', desc: 'Pix, cartão ou boleto pelo MercadoPago. No Pix libera em até 5 minutos.' },
  { Icon: Target,     titulo: 'Receba os picks',   desc: 'O acesso abre na sua conta e os picks do dia já aparecem no app.' },
]

export function PassosDaAssinatura() {
  return (
    <section className="bg-surface-1 border border-line rounded-lg p-5 sm:p-6">
      <h2 className="font-display text-base font-bold text-ink-1">Como funciona</h2>
      <p className="text-ink-3 text-sm mt-0.5">Três passos do plano até o primeiro pick.</p>

      <ol className="mt-6 grid gap-6 sm:grid-cols-3 sm:gap-4">
        {PASSOS.map(({ Icon, titulo, desc }, i) => (
          <li key={titulo} className="relative flex sm:flex-col items-start sm:items-center gap-4 sm:gap-0 sm:text-center">
            {/* Linha até o próximo passo · só no desktop, onde eles ficam lado a lado. */}
            {i < PASSOS.length - 1 && (
              <span
                aria-hidden="true"
                className="hidden sm:block absolute top-6 left-[calc(50%+36px)] right-[calc(-50%+36px)] h-0.5 rounded-full bg-gradient-to-r from-accent/60 to-accent/20"
              />
            )}
            <span className="relative shrink-0 w-12 h-12 rounded-full bg-accent/15 border border-accent/40 flex items-center justify-center text-accent-ink">
              <Icon className="w-5 h-5" aria-hidden="true" />
              <span className="absolute -top-1 -right-1 w-5 h-5 rounded-full bg-surface-0 border border-line text-[10px] font-bold text-ink-1 flex items-center justify-center">
                {i + 1}
              </span>
            </span>
            <span className="min-w-0 sm:mt-3">
              <span className="block text-ink-1 text-sm font-bold">{titulo}</span>
              <span className="block text-ink-3 text-xs leading-relaxed mt-0.5 sm:max-w-[26ch] sm:mx-auto">{desc}</span>
            </span>
          </li>
        ))}
      </ol>
    </section>
  )
}

const PERGUNTAS: Array<{ Icon: LucideIcon; q: string; a: React.ReactNode }> = [
  {
    Icon: RefreshCw,
    q: 'Vai cobrar sozinho todo mês?',
    a: SEM_RENOVACAO_AUTOMATICA,
  },
  {
    Icon: Wallet,
    q: 'Quais formas de pagamento vocês aceitam?',
    a: <>Pix, cartão ou boleto, tudo pelo <strong className="text-ink-1">MercadoPago</strong>. No Pix o acesso abre em até 5 minutos; no boleto, quando o banco compensa.</>,
  },
  {
    Icon: BarChart3,
    q: 'Como eu sei que os picks funcionam?',
    a: <>Todo pick publicado entra no <strong className="text-ink-1">histórico público</strong>, inclusive os que perderam, com win rate por liga, por jogo e por mês. Dá pra conferir antes de assinar.</>,
  },
  {
    Icon: TrendingUp,
    q: 'A IA garante lucro?',
    a: <>Não. Nenhum método garante. O que a IA faz é publicar só o que tem <strong className="text-ink-1">valor esperado positivo</strong> contra a odd da casa, e a gestão de banca ajuda a manter a stake sob controle. Aposte com responsabilidade.</>,
  },
  {
    Icon: Radio,
    q: 'Qual a diferença entre o Pick IA e o Pro?',
    a: <>O Pick IA abre todo o pré-jogo. O <strong className="text-ink-1">Pro</strong> soma os picks ao vivo e o agente de futebol, e dá pra testar grátis por 2 dias.</>,
  },
]

function Pergunta({ Icon, q, a, destaque, aberta, onToggle }: {
  Icon: LucideIcon; q: string; a: React.ReactNode; destaque?: boolean; aberta: boolean; onToggle: () => void
}) {
  return (
    <div className={cn('rounded-lg border bg-surface-0/40', destaque ? 'border-amber-500/40' : 'border-line')}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={aberta}
        className="w-full flex items-center gap-3 px-4 min-h-[52px] text-left touch-manipulation"
      >
        <span className={cn(
          'shrink-0 w-8 h-8 rounded-md border flex items-center justify-center',
          destaque ? 'border-amber-500/40 text-amber-400' : 'border-line text-ink-3',
        )}>
          <Icon className="w-4 h-4" aria-hidden="true" />
        </span>
        <span className="flex-1 text-xs font-bold uppercase tracking-wide text-ink-1">{q}</span>
        {aberta
          ? <X className="w-4 h-4 shrink-0 text-accent-ink" aria-hidden="true" />
          : <Plus className="w-4 h-4 shrink-0 text-ink-3" aria-hidden="true" />}
      </button>
      <div hidden={!aberta} className="px-4 pb-4 pl-[60px] text-sm text-ink-3 leading-relaxed">{a}</div>
    </div>
  )
}

export function FaqDaAssinatura() {
  // As duas primeiras nascem abertas: são as objeções que mais travam a compra.
  const [abertas, setAbertas] = useState<Set<number>>(() => new Set([0, 1]))
  const alternar = (i: number) => setAbertas(prev => {
    const s = new Set(prev)
    if (s.has(i)) s.delete(i); else s.add(i)
    return s
  })

  /* O menu lateral aponta pra /planos#faq, e o React Router não rola até a
     âncora sozinho. O atraso cobre os planos que chegam da API e empurram a
     seção pra baixo depois da montagem. */
  useEffect(() => {
    if (window.location.hash !== '#faq') return
    const t = setTimeout(() => document.getElementById('faq')?.scrollIntoView({ behavior: 'smooth' }), 400)
    return () => clearTimeout(t)
  }, [])

  return (
    <section id="faq" className="bg-surface-1 border border-line rounded-lg p-5 sm:p-6 scroll-mt-20">
      <h2 className="font-display text-base font-bold text-ink-1">Perguntas frequentes</h2>
      <p className="text-ink-3 text-sm mt-0.5">Respostas diretas sobre pagamento, acesso e resultados.</p>

      <div className="mt-5 space-y-2.5">
        {PERGUNTAS.map((p, i) => (
          <Pergunta key={p.q} {...p} aberta={abertas.has(i)} onToggle={() => alternar(i)} />
        ))}
        <Pergunta
          Icon={Headphones}
          q="Ficou com dúvida ou precisa de ajuda?"
          destaque
          aberta={abertas.has(PERGUNTAS.length)}
          onToggle={() => alternar(PERGUNTAS.length)}
          a={<>Fale com a gente pelo{' '}
            <a href={WA_SUPPORT} target="_blank" rel="noopener noreferrer" className="text-accent-ink font-semibold underline underline-offset-2">WhatsApp</a>.
            {' '}Problema com pagamento, acesso ou qualquer dúvida sobre os picks.</>}
        />
      </div>
    </section>
  )
}
