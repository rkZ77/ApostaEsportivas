import { useEffect, useState } from 'react'
import api from '../services/api'
import Marquee from './ui/Marquee'
import { cn } from '../lib/cn'

/*
 * Fita de ligas cobertas rolando sem fim.
 *
 * A lista vem do banco (/public/leagues), não de uma constante: a cobertura
 * entra e sai conforme a temporada de cada liga começa e acaba, e uma lista
 * fixa acabaria anunciando campeonato que a IA não está analisando.
 *
 * Sem JS de carrossel: são duas cópias do mesmo trilho com animação CSS. Um
 * carrossel de verdade aqui só somaria bytes, já que não há interação.
 */

export interface LeagueTeaser {
  league_id: number
  name: string
  logo_url: string
}

export default function LeagueMarquee({
  className,
  /** Fica sem cor até o hover. Usar quando a fita for pano de fundo. */
  muted,
}: {
  className?: string
  muted?: boolean
}) {
  const [leagues, setLeagues] = useState<LeagueTeaser[]>([])

  useEffect(() => {
    api.get('/public/leagues')
      .then(r => setLeagues(r.data ?? []))
      .catch(() => {})
  }, [])

  // Com poucas ligas o trilho não preenche a largura e a emenda entre as duas
  // cópias aparece como um salto. Repetir até passar de 12 itens resolve.
  if (leagues.length === 0) return null
  const items = leagues.length >= 12
    ? leagues
    : Array.from({ length: Math.ceil(12 / leagues.length) }, () => leagues).flat()

  return (
    <Marquee
      className={cn('py-2', className)}
      items={items.map((lg, i) => (
        <div
          key={`${lg.league_id}-${i}`}
          className="flex items-center gap-2.5 px-1"
          /* A fita já lista as ligas em texto pra quem lê a tela; repetir a
             lista duplicada só faria o leitor anunciar tudo duas vezes. */
          aria-hidden={i >= leagues.length ? 'true' : undefined}
        >
          <img
            src={lg.logo_url}
            alt=""
            width={22}
            height={22}
            loading="lazy"
            className={cn(
              'w-[22px] h-[22px] object-contain shrink-0 transition-all duration-2 ease-smooth',
              muted && 'grayscale opacity-50 hover:grayscale-0 hover:opacity-100',
            )}
            onError={e => (e.currentTarget.style.display = 'none')}
          />
          <span className="text-xs font-medium text-ink-3 whitespace-nowrap">{lg.name}</span>
        </div>
      ))}
    />
  )
}
