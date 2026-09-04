import { useState } from 'react'

function nameColor(name: string): string {
  const colors = [
    'bg-green-600', 'bg-blue-600', 'bg-purple-600', 'bg-orange-600',
    'bg-pink-600',  'bg-teal-600', 'bg-indigo-600', 'bg-rose-600',
  ]
  let hash = 0
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash)
  return colors[Math.abs(hash) % colors.length]
}

interface AvatarProps {
  name: string
  imageUrl?: string | null
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

const SIZE = {
  sm: 'w-7 h-7 text-xs',
  md: 'w-9 h-9 text-sm',
  lg: 'w-16 h-16 text-xl',
}

const SIZE_PX = {
  sm: 28,
  md: 36,
  lg: 64,
}

/* O ARQUIVO ESTATICO SOME A CADA DEPLOY, E O BANCO NAO (2026-09-04).
 *
 * `avatar_url` aponta pra `/static/avatars/<id>.<ext>`, gravado no disco do
 * container -- e container do Railway e' efemero: todo deploy sobe um novo e
 * leva os arquivos junto. O sintoma era todo mundo perder a foto e voltar pro
 * circulo de iniciais sempre que o site atualizava.
 *
 * Agora a foto tambem vive no banco, e esta funcao e' a segunda tentativa: o
 * 404 do arquivo estatico cai em `/api/auth/avatar/<id>`, que serve do banco E
 * reescreve o arquivo de passagem. Ou seja, o primeiro visitante depois do
 * deploy paga uma consulta e restaura o cache pra todos os outros.
 *
 * So' o proprio `<id>` do caminho e' reaproveitado: nada de texto de fora entra
 * na URL nova. */
function rotaDoBanco(imageUrl: string): string | null {
  const m = imageUrl.match(/\/static\/avatars\/(\d+)\.[a-z]+$/i)
  return m ? `/api/auth/avatar/${m[1]}` : null
}

export default function Avatar({ name, imageUrl, size = 'md', className = '' }: AvatarProps) {
  /* 0 = a URL que veio; 1 = a rota do banco; 2 = desistiu, mostra as iniciais.
     Um contador e nao um booleano porque sao DUAS tentativas, e um `onError`
     que so' liga uma flag nunca chega na segunda. */
  const [tentativa, setTentativa] = useState(0)

  const initials = name
    .split(' ')
    .slice(0, 2)
    .map(w => w[0]?.toUpperCase() ?? '')
    .join('')

  // URL relativa funciona tanto em dev (proxy Vite /static -> 8000) quanto em prod (mesmo domínio)
  const doBanco = imageUrl ? rotaDoBanco(imageUrl) : null
  const src = !imageUrl || tentativa >= 2 ? null
            : tentativa === 0 ? imageUrl
            : doBanco

  if (src) {
    return (
      <img
        src={src}
        alt={name}
        width={SIZE_PX[size]}
        height={SIZE_PX[size]}
        className={`${SIZE[size]} rounded-full object-cover shrink-0 ${className}`}
        /* Sem rota do banco (avatar do Google, por exemplo) a primeira falha ja'
           vai direto pras iniciais · nao ha' segunda fonte pra tentar. */
        onError={() => setTentativa(t => (t === 0 && doBanco ? 1 : 2))}
      />
    )
  }

  return (
    <div className={`${SIZE[size]} ${nameColor(name)} rounded-full flex items-center justify-center font-black text-ink-1 shrink-0 select-none ${className}`}>
      {initials}
    </div>
  )
}
