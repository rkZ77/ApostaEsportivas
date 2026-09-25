/*
 * Escudos. Este arquivo JÁ era o lugar certo -- o que faltava era os
 * consumidores usarem: LivePicks e LivePicksFeed mantinham cópias locais de
 * `TeamLogo`, e o feed chegava a importar `LeagueLogo` daqui enquanto
 * redefinia o `TeamLogo` por cima. As cópias não tinham `loading="lazy"`,
 * então a versão duplicada era pior que a original.
 */
import { useState } from 'react'
import { Globe } from 'lucide-react'
import { cn } from '../lib/cn'
import { paisDaLiga } from '../lib/paisDaLiga'
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

/*
 * ESCUDO DE LIGA SOBRE FUNDO CLARO (2026-09-06, pedido do usuário).
 *
 * Boa parte dos emblemas de competição é monocromática em PRETO -- Ligue 1,
 * Serie A, Eredivisie -- e o provedor entrega o PNG com fundo transparente.
 * No tema escuro do site isso vira um quadrado invisível: a linha mostrava o
 * nome da liga e um buraco onde devia estar o escudo, e só nas ligas de logo
 * colorido (Bundesliga) ele aparecia. Parecia imagem quebrada.
 *
 * A moldura clara resolve nos dois temas e para os dois tipos de emblema: o
 * preto passa a ter contraste, e o colorido continua legível sobre branco --
 * é a mesma solução que os placares usam. `opacity` saiu junto: escurecer um
 * logo que já sumia era o outro metade do problema.
 */
/*
 * MOLDURA SÓ QUANDO O ESCUDO PRECISA (2026-09-25, pedido do usuário).
 *
 * A moldura branca de 06/09 resolveu os emblemas pretos (Ligue 1, Serie A,
 * Eredivisie) no tema escuro, mas foi pra TODOS: escudo colorido também ganhava
 * um quadrado branco, e a lista virava uma coluna de etiquetas.
 *
 * Agora o escudo é medido quando carrega: quanto dos pixels some contra o fundo,
 * num canvas de 24px (o proxy serve da mesma origem, então o canvas lê).
 *   - escuro (preto no transparente) -> fundo claro, só no tema escuro
 *   - claro (branco no transparente) -> fundo escuro, só no tema claro
 *   - o resto fica sem moldura nos dois temas
 * O resultado fica guardado por id na sessão: a mesma liga aparece em várias
 * listas da página e não precisa ser medida de novo.
 */
type TomDoEscudo = 'escuro' | 'claro' | 'normal'
const TOM_DO_ESCUDO = new Map<number, TomDoEscudo>()

function medirTom(img: HTMLImageElement): TomDoEscudo {
  try {
    const lado = 24
    const c = document.createElement('canvas')
    c.width = lado; c.height = lado
    const ctx = c.getContext('2d', { willReadFrequently: true })
    if (!ctx) return 'normal'
    ctx.drawImage(img, 0, 0, lado, lado)
    const px = ctx.getImageData(0, 0, lado, lado).data
    // CONTRASTE DE CADA PIXEL CONTRA O FUNDO (fórmula da WCAG), e não brilho
    // médio nem luminância crua. Medido nos 19 escudos da cobertura: pela média,
    // o troféu dourado da Sudamericana a deixava sem moldura; pela luminância, o
    // vermelho da Bundesliga (5:1 no preto, bem visível) contava como escuro; e
    // o azul-marinho da Eredivisie (1,4:1, some) contava como visível.
    const lin = (c: number) => { c /= 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4 }
    let transparentes = 0, somemNoEscuro = 0, somemNoClaro = 0, n = 0
    for (let i = 0; i < px.length; i += 4) {
      if (px[i + 3] < 128) { transparentes++; continue }
      const L = 0.2126 * lin(px[i]) + 0.7152 * lin(px[i + 1]) + 0.0722 * lin(px[i + 2])
      if ((L + 0.05) / 0.054 < 2) somemNoEscuro++      // fundo do tema escuro, L ~ 0.004
      if (1.05 / (L + 0.05) < 1.6) somemNoClaro++       // fundo do tema claro, L ~ 1
      n++
    }
    // Escudo que já vem num quadrado cheio (Série A, Liga Portugal) tem fundo
    // próprio: moldura por trás dele seria só uma borda a mais.
    if (n < 20 || transparentes < (lado * lado) * 0.05) return 'normal'
    // Limites com folga dos dois lados: o escudo normal mais escuro (2.
    // Bundesliga) some 8% no preto e o escuro mais claro (Sudamericana) ~50%;
    // no claro, a Championship some ~56% e não precisa de fundo.
    return somemNoEscuro / n > 0.4 ? 'escuro' : somemNoClaro / n > 0.75 ? 'claro' : 'normal'
  } catch {
    return 'normal'
  }
}

export function LeagueLogo({ id, name, size = 16 }: { id?: number; name?: string; size?: number }) {
  const src = LEAGUE_LOGO(id)
  const [tom, setTom] = useState<TomDoEscudo>(() => (id != null && TOM_DO_ESCUDO.get(id)) || 'normal')
  if (!src) return null
  return (
    <span
      className={cn(
        'inline-flex items-center justify-center shrink-0 rounded-[3px] p-px',
        // Tema escuro é o padrão; o claro é :root[data-theme="light"].
        tom === 'escuro' && 'bg-white/90 [[data-theme=light]_&]:bg-transparent',
        tom === 'claro' && '[[data-theme=light]_&]:bg-neutral-800',
      )}
      style={{ width: size + 3, height: size + 3 }}
    >
      <img src={src} alt={name ?? ''} width={size} height={size} loading="lazy"
        className="object-contain" style={{ width: size, height: size }}
        onLoad={e => {
          if (id == null) return
          const t = TOM_DO_ESCUDO.get(id) ?? medirTom(e.currentTarget)
          TOM_DO_ESCUDO.set(id, t)
          setTom(t)
        }}
        onError={e => (e.currentTarget.style.display = 'none')} />
    </span>
  )
}

/*
 * BANDEIRA E PAÍS DA LIGA (2026-09-25), no molde da tabela de ligas da
 * API-Football: bandeira pequena e o nome do país ao lado.
 *
 * A imagem vem da flagcdn em PNG de 40px (100 a 500 bytes cada) · o SVG da
 * Espanha sozinho tinha 153KB. Competição de vários países mostra um globo.
 * Liga fora do mapa (lib/paisDaLiga) não mostra nada, em vez de chutar.
 */
export function Bandeira({ codigo, pais, className }: { codigo: string | null; pais: string; className?: string }) {
  if (!codigo) {
    return <Globe className={cn('w-3.5 h-3.5 shrink-0 text-ink-4', className)} aria-label={pais} />
  }
  return (
    <img
      src={`https://flagcdn.com/w40/${codigo}.png`}
      alt={pais}
      width={16}
      height={12}
      loading="lazy"
      className={cn('w-4 h-3 shrink-0 rounded-[2px] object-cover ring-1 ring-black/10', className)}
      onError={e => (e.currentTarget.style.display = 'none')}
    />
  )
}

export function PaisDaLigaTag({ id, className, soBandeira = false }: {
  id?: number | null
  className?: string
  /** Só a bandeira, pra linhas apertadas (chips, celular). */
  soBandeira?: boolean
}) {
  const p = paisDaLiga(id)
  if (!p) return null
  if (soBandeira) return <Bandeira codigo={p.bandeira} pais={p.pais} className={className} />
  return (
    <span className={cn('inline-flex items-center gap-1.5 text-[11px] text-ink-4 min-w-0', className)}>
      <Bandeira codigo={p.bandeira} pais={p.pais} />
      <span className="truncate">{p.pais}</span>
    </span>
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
