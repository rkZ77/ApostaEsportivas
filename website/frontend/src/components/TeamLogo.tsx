/*
 * Escudos. Este arquivo JÁ era o lugar certo -- o que faltava era os
 * consumidores usarem: LivePicks e LivePicksFeed mantinham cópias locais de
 * `TeamLogo`, e o feed chegava a importar `LeagueLogo` daqui enquanto
 * redefinia o `TeamLogo` por cima. As cópias não tinham `loading="lazy"`,
 * então a versão duplicada era pior que a original.
 */
import { useState } from 'react'
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

/* Iniciais de "Erick Pulgar" -> "EP". Nome de uma palavra devolve duas letras
   dela, que é melhor que uma letra sozinha perdida no círculo. */
function iniciaisDoNome(nome: string): string {
  const partes = nome.trim().split(/\s+/).filter(Boolean)
  if (partes.length === 0) return '?'
  if (partes.length === 1) return partes[0].slice(0, 2).toUpperCase()
  return (partes[0][0] + partes[partes.length - 1][0]).toUpperCase()
}

/*
 * FOTO DO JOGADOR.
 *
 * Vem do mesmo provedor dos escudos, pelo mesmo proxy do backend
 * (/api/proxy/player/<id>.png), então herda o cache em disco e o corte para
 * 64px. O pick de jogador é sobre uma PESSOA e o card mostrava só o nome dela.
 *
 * AS INICIAIS NÃO SÃO FALLBACK DE ERRO, SÃO O FUNDO. Elas ficam desenhadas
 * embaixo e a foto entra por cima; jogador sem foto no provedor (que existe, e
 * em liga pequena é comum) não deixa buraco nem quadrado quebrado no card, e
 * não é preciso saber de antemão quem tem foto.
 */
export function PlayerPhoto({ id, name, size = 36, fonte = 'player' }: {
  id?: number | null
  name: string
  size?: number
  /** De qual bucket do provedor vem a foto. `referee` (2026-09-05) reusa o
   *  mesmo componente porque o problema é o mesmo: uma PESSOA identificada por
   *  nome, com foto que às vezes existe e às vezes não. */
  fonte?: 'player' | 'referee'
}) {
  const [falhou, setFalhou] = useState(false)
  return (
    <span
      className="relative shrink-0 rounded-full overflow-hidden bg-surface-3 border border-line
                 grid place-items-center select-none"
      style={{ width: size, height: size }}
      title={name}
    >
      <span className="font-black text-ink-4" style={{ fontSize: Math.round(size * 0.32) }}>
        {iniciaisDoNome(name)}
      </span>
      {id != null && !falhou && (
        <img
          src={`/api/proxy/${fonte}/${id}.png`}
          alt={name}
          width={size}
          height={size}
          loading="lazy"
          className="absolute inset-0 w-full h-full object-cover"
          onError={() => setFalhou(true)}
        />
      )}
    </span>
  )
}
