const API_BASE = (import.meta as any).env?.VITE_API_URL ?? 'http://localhost:8000'

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

export default function Avatar({ name, imageUrl, size = 'md', className = '' }: AvatarProps) {
  const initials = name
    .split(' ')
    .slice(0, 2)
    .map(w => w[0]?.toUpperCase() ?? '')
    .join('')

  const src = imageUrl
    ? imageUrl.startsWith('http') ? imageUrl : `${API_BASE}${imageUrl}`
    : null

  if (src) {
    return (
      <img
        src={src}
        alt={name}
        className={`${SIZE[size]} rounded-full object-cover shrink-0 ${className}`}
        onError={e => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
      />
    )
  }

  return (
    <div className={`${SIZE[size]} ${nameColor(name)} rounded-full flex items-center justify-center font-black text-white shrink-0 select-none ${className}`}>
      {initials}
    </div>
  )
}
