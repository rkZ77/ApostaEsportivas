/*
 * Escudos. Este arquivo JÁ era o lugar certo -- o que faltava era os
 * consumidores usarem: LivePicks e LivePicksFeed mantinham cópias locais de
 * `TeamLogo`, e o feed chegava a importar `LeagueLogo` daqui enquanto
 * redefinia o `TeamLogo` por cima. As cópias não tinham `loading="lazy"`,
 * então a versão duplicada era pior que a original.
 */
import { escudoDoTime } from '../lib/aoVivo'

/* Sem exceção local para a liga 1 (Copa do Mundo). Ela existia porque o escudo
   do torneio era servido de `public/logo-copa-mundo.png` · um PNG de 90KB para
   aparecer a 16px. A Copa acabou em 2026-08-11 e só volta em 2030; o que resta
   dela são picks históricos, e para esses o proxy serve o escudo igual a
   qualquer outra liga. Uma exceção a menos para lembrar. */
const LEAGUE_LOGO = (id?: number) => id ? `/api/proxy/league/${id}.png` : null

export function TeamLogo({ id, name, size = 22 }: { id?: number; name: string; size?: number }) {
  const src = escudoDoTime(id)
  if (!src) return null
  return (
    <img src={src} alt={name} width={size} height={size} loading="lazy"
      className="object-contain shrink-0" style={{ width: size, height: size }}
      onError={e => (e.currentTarget.style.display = 'none')} />
  )
}

export function LeagueLogo({ id, name, size = 16 }: { id?: number; name?: string; size?: number }) {
  const src = LEAGUE_LOGO(id)
  if (!src) return null
  return (
    <img src={src} alt={name ?? ''} width={size} height={size} loading="lazy"
      className="object-contain shrink-0 opacity-70" style={{ width: size, height: size }}
      onError={e => (e.currentTarget.style.display = 'none')} />
  )
}
