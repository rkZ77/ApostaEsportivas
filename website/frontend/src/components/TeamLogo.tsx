const TEAM_LOGO = (id?: number) => id ? `/api/proxy/team/${id}.png` : null
const LOCAL_LEAGUE_LOGOS: Record<number, string> = { 1: '/logo-copa-mundo.png' }
const LEAGUE_LOGO = (id?: number) =>
  id ? (LOCAL_LEAGUE_LOGOS[id] ?? `/api/proxy/league/${id}.png`) : null

export function TeamLogo({ id, name, size = 22 }: { id?: number; name: string; size?: number }) {
  const src = TEAM_LOGO(id)
  if (!src) return null
  return (
    <img src={src} alt={name} width={size} height={size} loading="lazy"
      className="object-contain shrink-0" style={{ width: size, height: size }}
      onError={e => (e.currentTarget.style.display = 'none')} />
  )
}

export function LeagueLogo({ id, name }: { id?: number; name?: string }) {
  const src = LEAGUE_LOGO(id)
  if (!src) return null
  return (
    <img src={src} alt={name ?? ''} width={16} height={16} loading="lazy"
      className="w-4 h-4 object-contain shrink-0 opacity-70"
      onError={e => (e.currentTarget.style.display = 'none')} />
  )
}
