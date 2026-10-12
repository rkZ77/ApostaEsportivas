import { useLocation, useParams, useSearchParams } from 'react-router-dom'
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
    status: q.get('st') ?? undefined,
    home_goals: num('gc') ?? null, away_goals: num('gf') ?? null,
  }
  const titulo = jogo.home_team && jogo.away_team ? `${jogo.home_team} x ${jogo.away_team}` : 'Raio-X do jogo'
  /* Veio da lista: voltar é VOLTAR (12/10/2026), e a lista reaparece no dia,
     filtro e rolagem em que estava (ver Fixtures, `estadoDaLista`). Abrir
     /jogos de novo empilhava uma lista nova, no dia de hoje e no topo. Link
     aberto direto (compartilhado) não tem para onde voltar: vai para /jogos. */
  const daLista = !!(useLocation().state as { daLista?: boolean } | null)?.daLista

  return (
    <PageShell title={titulo} noindex width="narrow" footer={false}
      bar={{ back: daLista ? true : '/jogos', title: 'Raio-X do jogo' }}>
      {/* Plano gratuito: o placar e as abas trancadas (12/10/2026), em vez
          de um cartão de "é para assinantes" no lugar da página inteira. */}
      <RaioXDoJogo jogo={jogo} trancado={!pode} />
      {pode && <BandejaDoBilhete />}
    </PageShell>
  )
}
