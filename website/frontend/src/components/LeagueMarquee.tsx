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
  /** `false` = competição encerrada, só histórico. Fora da fita. */
  ativa?: boolean
}

/*
 * A resposta é buscada uma vez por carregamento de página, não uma vez por
 * fita. A Home monta duas fitas cruzadas, e como cada uma tinha seu próprio
 * useEffect, as duas montavam juntas e disparavam a mesma requisição em
 * paralelo · duas conexões novas ao banco para a mesma lista de ligas.
 *
 * Guardar a Promise (e não o resultado) é o que resolve o caso das duas
 * montarem no mesmo tique: a segunda encontra a chamada já em voo e aguarda
 * essa, em vez de começar outra. Falha limpa a variável para a próxima
 * montagem poder tentar de novo.
 */
let _leaguesPromise: Promise<LeagueTeaser[]> | null = null

function fetchLeagues(): Promise<LeagueTeaser[]> {
  if (!_leaguesPromise) {
    _leaguesPromise = api.get('/public/leagues')
      // A rota devolve o histórico junto porque a tela de Estatísticas precisa
      // dele. Aqui não: a fita é promessa de cobertura, e anunciar a Copa do
      // Mundo (encerrada em agosto de 2026) é prometer análise que não vem.
      .then(r => ((r.data ?? []) as LeagueTeaser[]).filter(l => l.ativa !== false))
      .catch(err => { _leaguesPromise = null; throw err })
  }
  return _leaguesPromise
}

export default function LeagueMarquee({
  className,
  /** Roda no sentido contrário. Usado pra cruzar duas fitas. */
  reverse,
  /*
   * Quem manda buscar. Existe porque esta fita fica lá embaixo na Home e a
   * chamada dela saía junto com as três do topo, disputando o único worker do
   * servidor (ver hooks/usePertoDaTela.ts). O padrão é `true` para que qualquer
   * outro lugar que monte a fita continue funcionando como antes.
   */
  carregar = true,
}: {
  className?: string
  reverse?: boolean
  carregar?: boolean
}) {
  const [leagues, setLeagues] = useState<LeagueTeaser[]>([])

  useEffect(() => {
    if (!carregar) return
    let vivo = true
    fetchLeagues()
      .then(l => { if (vivo) setLeagues(Array.isArray(l) ? l : []) })
      .catch(() => {})
    return () => { vivo = false }
  }, [carregar])

  if (leagues.length === 0) return null

  /*
   * Cada liga entra uma vez, e só.
   *
   * Antes a lista era repetida até passar de 12 itens, pra tapar um salto na
   * emenda da fita. Com 8 ligas cadastradas isso punha a mesma liga quatro
   * vezes no trilho · às vezes duas delas visíveis lado a lado, o que lia como
   * cobertura inflada de propósito. O salto era defeito do Marquee e foi
   * corrigido lá; aqui não sobrou motivo para repetir nada.
   */
  return (
    <Marquee
      reverse={reverse}
      className={cn('py-2', className)}
      spacing="pr-10"
      speed={40}
      items={leagues.map(lg => (
        <div key={lg.league_id} className="flex items-center gap-2.5 px-1">
          <img
            src={lg.logo_url}
            alt=""
            width={32}
            height={32}
            loading="lazy"
            /* Sem grayscale: o escudo em cor é o que o olho reconhece, e era
               justamente isso que a fita apagava. */
            className="w-8 h-8 object-contain shrink-0"
            onError={e => (e.currentTarget.style.display = 'none')}
          />
          <span className="text-sm font-medium text-ink-2 whitespace-nowrap">{lg.name}</span>
        </div>
      ))}
    />
  )
}
