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

export default function Avatar({ name, imageUrl, size = 'md', className = '' }: AvatarProps) {
  const [imgError, setImgError] = useState(false)

  const initials = name
    .split(' ')
    .slice(0, 2)
    .map(w => w[0]?.toUpperCase() ?? '')
    .join('')

  // URL relativa funciona tanto em dev (proxy Vite /static -> 8000) quanto em prod (mesmo domínio)
  const src = imageUrl && !imgError
    ? (imageUrl.startsWith('http') ? imageUrl : imageUrl)
    : null

  if (src) {
    return (
      <img
        src={src}
        alt={name}
        width={SIZE_PX[size]}
        height={SIZE_PX[size]}
        className={`${SIZE[size]} rounded-full object-cover shrink-0 ${className}`}
        onError={() => setImgError(true)}
      />
    )
  }

  return (
    <div className={`${SIZE[size]} ${nameColor(name)} rounded-full flex items-center justify-center font-black text-ink-1 shrink-0 select-none ${className}`}>
      {initials}
    </div>
  )
}
