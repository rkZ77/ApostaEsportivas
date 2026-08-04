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
  /** Roda no sentido contrário. Usado pra cruzar duas fitas. */
  reverse,
}: {
  className?: string
  reverse?: boolean
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
      reverse={reverse}
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
            /* Sem grayscale: o escudo em cor é o que o olho reconhece, e era
               justamente isso que a fita apagava. */
            className="w-[26px] h-[26px] object-contain shrink-0" 
            onError={e => (e.currentTarget.style.display = 'none')}
          />
          <span className="text-xs font-medium text-ink-3 whitespace-nowrap">{lg.name}</span>
        </div>
      ))}
    />
  )
}
