import { useId, useState } from 'react'
import { ChevronDown, HelpCircle } from 'lucide-react'
import { cn } from '../../lib/cn'

/**
 * "Como funciona" de um produto · fechado por padrão, a um toque de distância.
 *
 * POR QUE ELE NASCE FECHADO (2026-08-29, pedido do usuário)
 * ---------------------------------------------------------
 * Cada aba de Picks abria com um bloco de dois a quatro parágrafos explicando
 * o produto. O texto é bom e a explicação precisa existir · o problema é
 * quando ela aparece: TODA vez, para TODO mundo, acima dos picks.
 *
 * No celular, que é onde o site vive, isso empurrava o primeiro card para
 * baixo da dobra. Quem entra na aba pela vigésima vez não está lendo aquilo
 * há dezenove visitas, e mesmo assim rola por cima dele todo dia.
 *
 * Fechado, o produto abre no que interessa (o pick) e a explicação continua
 * ali, nomeada, para quem quiser rever · que era o pedido: "conseguir
 * reescolher o como funciona".
 *
 * O PLACAR FICA DENTRO. Ele é a resposta a "e isso funciona?", que é a mesma
 * pergunta que o texto responde · e é o número que muda com o tempo, então
 * quem volta para consultar volta pelos dois juntos.
 *
 * Estado local, e não em localStorage, de propósito: lembrar que a pessoa
 * abriu ontem faria a aba voltar a nascer com a parede de texto, que é
 * justamente o que este componente existe para evitar.
 */
export default function ComoFunciona({
  titulo,
  cor = 'text-accent-ink',
  borda = 'border-line',
  fundo = 'bg-surface-1',
  children,
  className,
}: {
  /** "O que são os Picks VIP?" · a pergunta que o bloco responde. */
  titulo: string
  /** Cor do produto, para o título. */
  cor?: string
  borda?: string
  fundo?: string
  children: React.ReactNode
  className?: string
}) {
  const [aberto, setAberto] = useState(false)
  const id = useId()

  return (
    <div className={cn('rounded-lg border', borda, fundo, className)}>
      <button
        type="button"
        onClick={() => setAberto(a => !a)}
        aria-expanded={aberto}
        aria-controls={id}
        /* min-h de 44px: é o alvo de toque mínimo, e este é um controle que
           existe justamente para a tela pequena. */
        className="w-full flex items-center gap-2 px-4 py-3 min-h-[44px] text-left touch-manipulation"
      >
        <HelpCircle className={cn('w-4 h-4 shrink-0', cor)} />
        <span className={cn('font-display text-sm font-bold', cor)}>{titulo}</span>
        <ChevronDown
          className={cn(
            'w-4 h-4 ml-auto shrink-0 text-ink-4 transition-transform duration-200 motion-reduce:transition-none',
            aberto && 'rotate-180',
          )}
        />
      </button>
      {/* Sem animação de altura: o conteúdo tem tamanho variável (alguns
          produtos têm placar, outros não) e medir isso a cada abertura custa
          mais do que a animação entrega. */}
      <div id={id} hidden={!aberto} className="px-4 pb-4 -mt-1">
        <div className="space-y-2 text-sm text-ink-2 leading-relaxed">{children}</div>
      </div>
    </div>
  )
}
