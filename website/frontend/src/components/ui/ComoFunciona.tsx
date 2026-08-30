import { useId, useState } from 'react'
import { ChevronDown, HelpCircle } from 'lucide-react'
import { cn } from '../../lib/cn'

/**
 * "Como funciona" de um produto · aberto, e a um toque de sair da frente.
 *
 * NASCE ABERTO, E FECHA NUM TOQUE (2026-08-30, decisão do usuário)
 * ----------------------------------------------------------------
 * A primeira versão (29/08) nascia fechada, pra o primeiro pick caber na tela
 * do celular. O usuário inverteu no dia seguinte, e a razão dele vence a
 * minha: quem chega pela primeira vez precisa saber o que está comprando, e
 * uma explicação que só existe atrás de um toque é uma explicação que a maior
 * parte das pessoas nunca vai ler.
 *
 * O que resolve o problema do espaço é o toque para FECHAR, não o de abrir:
 * quem já conhece o produto fecha uma vez e segue; quem não conhece lê sem ter
 * que descobrir que havia algo ali.
 *
 * O PLACAR FICA DENTRO. Ele é a resposta a "e isso funciona?", que é a mesma
 * pergunta que o texto responde · e é o número que muda com o tempo, então
 * quem volta para consultar volta pelos dois juntos.
 *
 * Estado local, e não em localStorage, de propósito: guardar a escolha entre
 * sessões parece atencioso e transforma a explicação em algo que some pra
 * sempre depois de um toque acidental.
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
  const [aberto, setAberto] = useState(true)
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
