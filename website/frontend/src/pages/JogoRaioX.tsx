import { useParams, useSearchParams, Link } from 'react-router-dom'
import { Lock } from 'lucide-react'
import PageShell from '../components/PageShell'
import RaioXDoJogo from '../components/jogos/RaioXDoJogo'
import BandejaDoBilhete from '../components/jogos/BandejaDoBilhete'
import { useAuth } from '../context/AuthContext'

/*
 * O Raio-X de um jogo em página própria (2026-10-06).
 *
 * No celular, tocar num jogo da aba Jogos abre AQUI, e não numa folha por cima
 * da lista: a página tem endereço (dá pra mandar o link do jogo), o botão de
 * voltar do aparelho funciona como a pessoa espera, e o Raio-X ganha a tela
 * inteira, que é o que uma lista de 25 jogadores precisa.
 *
 * Os times vêm na query (?home=&away=&league=) porque o jogo pode ser de uma
 * data que a coleta ainda não trouxe pro banco · ver routers/fixtures.py.
 */
export default function JogoRaioX() {
  const { fixtureId } = useParams()
  const [q] = useSearchParams()
  const { isVip, isAdmin, user } = useAuth()
  const pode = isVip || isAdmin || user?.plan === 'trial'
  const num = (k: string) => (q.get(k) ? Number(q.get(k)) : undefined)

  const jogo = {
    fixture_id: Number(fixtureId),
    home_team_id: num('home'), away_team_id: num('away'), league_id: num('league'),
    league_name: q.get('liga') ?? undefined,
    home_team: q.get('casa') ?? undefined, away_team: q.get('fora') ?? undefined,
    match_datetime: q.get('quando'),
  }
  const titulo = jogo.home_team && jogo.away_team ? `${jogo.home_team} x ${jogo.away_team}` : 'Raio-X do jogo'

  return (
    <PageShell title={titulo} noindex width="narrow" footer={false}
      bar={{ back: '/fixtures', title: 'Raio-X do jogo' }}>
      {pode ? (
        <>
          <RaioXDoJogo jogo={jogo} />
          <BandejaDoBilhete />
        </>
      ) : (
        <div className="card p-8 text-center">
          <Lock className="mx-auto text-yellow-400 mb-3" size={28} />
          <h2 className="text-lg font-bold text-ink-1">Raio-X é para assinantes</h2>
          <p className="text-sm text-ink-2 mt-2 mb-5">
            Taxa de acerto por linha, jogadores com histórico jogo a jogo, confronto e árbitro.
          </p>
          <Link to="/checkout" className="inline-flex h-12 items-center px-6 rounded-lg bg-yellow-400 text-on-fill font-black">
            Assinar
          </Link>
        </div>
      )}
    </PageShell>
  )
}
