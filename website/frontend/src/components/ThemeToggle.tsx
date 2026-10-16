import { Moon, Sun } from 'lucide-react'
import { alternarTema } from '../lib/theme'
import { useTema } from '../hooks/useTema'
import { cn } from '../lib/cn'

/*
 * Troca de tema · um botao so', do lado do sino.
 *
 * Nao e' um menu com tres opcoes (claro/escuro/sistema): sao dois estados e o
 * resultado aparece na hora, entao a propria tela ja diz em qual deles voce
 * esta. Um menu obrigaria dois toques pra fazer o que um toque faz.
 *
 * O icone mostra o tema PARA ONDE se vai, nao o atual · e o que o botao faz
 * quando voce aperta. E' por isso que no escuro aparece um sol.
 *
 * As duas camadas ficam empilhadas e trocam por opacidade e giro em vez de uma
 * sair do DOM: assim a largura do botao nao pula no meio da transicao e a barra
 * inteira nao se reposiciona por causa de um icone.
 */
export default function ThemeToggle({ className }: { className?: string }) {
  const tema = useTema()
  const claro = tema === 'light'

  return (
    <button
      type="button"
      onClick={alternarTema}
      aria-label={claro ? 'Mudar para o tema escuro' : 'Mudar para o tema claro'}
      title={claro ? 'Tema escuro' : 'Tema claro'}
      className={cn(
        'relative p-2 text-ink-2 hover:text-ink-1 transition-colors',
        className,
      )}
    >
      {/* Caixa de tamanho fixo: as duas camadas sao absolutas e nao ocupam
          espaco, entao alguem precisa reservar os 20px. */}
      <span className="relative block w-5 h-5">
        <Sun
          className={cn(
            'absolute inset-0 w-5 h-5 transition-all duration-2 ease-smooth',
            claro ? 'opacity-0 -rotate-90 scale-50' : 'opacity-100 rotate-0 scale-100',
          )}
        />
        <Moon
          className={cn(
            'absolute inset-0 w-5 h-5 transition-all duration-2 ease-smooth',
            claro ? 'opacity-100 rotate-0 scale-100' : 'opacity-0 rotate-90 scale-50',
          )}
        />
      </span>
    </button>
  )
}
