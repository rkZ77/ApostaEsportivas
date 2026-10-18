import { cn } from '../../lib/cn'

/* Arquivo próprio (18/10/2026) pra página pública de jogo (/jogo/<id>) usar
 * sem levar junto os 93 KB do RaioXDoJogo, de onde ele saiu. */
export function FormaPontos({ forma, tamanho = 'md' }: { forma: string[]; tamanho?: 'sm' | 'md' }) {
  if (!forma.length) return null
  const cor: Record<string, string> = {
    V: 'bg-green-500 text-on-fill', E: 'bg-surface-3 text-ink-2', D: 'bg-red-500 text-on-fill',
  }
  return (
    <div className="flex gap-1" aria-label={`Últimos jogos: ${forma.join(' ')}`}>
      {/* Do mais antigo pro mais recente, da esquerda pra direita: é como
          qualquer placar mostra, e o último jogo fica na ponta onde o olho
          termina de ler. */}
      {[...forma].reverse().map((r, i) => (
        <span key={i} className={cn(
          'grid place-items-center rounded font-black',
          tamanho === 'md' ? 'w-5 h-5 text-[10px]' : 'w-3.5 h-3.5 text-[8px]',
          cor[r] ?? cor.E,
        )}>{r}</span>
      ))}
    </div>
  )
}
