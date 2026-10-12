import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import { Clock } from 'lucide-react'
import { useNotifications } from '../context/NotificationContext'
import CartaoDeAviso, { timesDoAviso } from './ui/CartaoDeAviso'

/*
 * "O jogo do seu bilhete começa às 16:00" · aviso EM TELA (12/10/2026).
 *
 * Quem monta um bilhete no Raio-X quer acompanhar o jogo, e o aviso chega
 * pouco antes do apito: dá tempo de conferir a escalação no Raio-X ou abrir o
 * jogo. Mesmo cartão do canto do ao vivo e dos resultados, no tom neutro: não
 * é oportunidade nem resultado, é lembrete.
 */

const TEMPO_EM_TELA = 15_000
const FORA_DE = ['/checkout', '/login']

export default function JogoComecandoToast() {
  const { jogoComecando, dismissJogoComecando } = useNotifications()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const [visivel, setVisivel] = useState(false)
  const bloqueado = FORA_DE.some(r => pathname.startsWith(r))

  useEffect(() => {
    setVisivel(!!jogoComecando && !bloqueado)
  }, [jogoComecando?.id, bloqueado])

  const fechar = () => { setVisivel(false); dismissJogoComecando() }
  const fixtureId = jogoComecando?.payload?.fixture_id

  return (
    <AnimatePresence>
      {visivel && jogoComecando && (
        <CartaoDeAviso
          key={jogoComecando.id}
          tom="neutro"
          selo={<>Jogo do seu bilhete</>}
          icone={<Clock className="w-3 h-3" strokeWidth={3} aria-hidden="true" />}
          titulo={jogoComecando.title}
          times={timesDoAviso(jogoComecando.title, jogoComecando.payload)}
          texto={jogoComecando.body}
          acao={fixtureId
            ? { rotulo: 'Abrir Raio-X', onClick: () => { fechar(); navigate(`/jogos/${fixtureId}`) } }
            : { rotulo: 'Ver bilhete', onClick: () => { fechar(); navigate(jogoComecando.url || '/picks#minhas_apostas') } }}
          onFechar={fechar}
          duracaoMs={TEMPO_EM_TELA}
        />
      )}
    </AnimatePresence>
  )
}
