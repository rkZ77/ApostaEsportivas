import { useState } from 'react'
import { Helmet } from 'react-helmet-async'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Crown, Check, Mail } from 'lucide-react'

import api from '../services/api'
import PublicNav from '../components/PublicNav'
import { useAuth } from '../context/AuthContext'

/*
 * O PASSO QUE FALTA · tela imediatamente depois do cadastro.
 *
 * POR QUE ELA EXISTE. O site inteiro vende "2 dias de VIP grátis", e desde a
 * saída do CPF (18/08) o trial só nasce quando o contato é provado, no link do
 * e-mail ou no código do WhatsApp (ver `_ativar_trial_se_elegivel` no backend).
 * Quem terminava o cadastro ia parar direto em /picks como FREE, com o tour de
 * boas-vindas na frente e o aviso de confirmar o e-mail represado atrás dele:
 * a recompensa prometida três telas antes não aparecia em nenhuma. É o
 * vazamento mais caro do funil, porque acontece depois de a pessoa já ter
 * feito o trabalho todo.
 *
 * POR QUE É PÁGINA, E NÃO UM ESTADO DENTRO DO Login. A primeira versão era um
 * `if` no Login e nunca chegou a aparecer: `register()` já autentica, e o
 * <PublicRoute> manda quem está logado de /login para /picks (App.tsx). Como
 * página própria, fora daquele guarda, ela sobrevive inclusive a um F5.
 *
 * NADA AQUI É OBRIGATÓRIO. O link de baixo entra no site do mesmo jeito, no
 * plano free, que é exatamente o que acontecia antes sem ninguém explicar.
 */
export default function ConfirmarEmail() {
  const { user } = useAuth()
  const { state } = useLocation() as { state?: { email?: string } }
  const navigate = useNavigate()

  const [enviando, setEnviando]   = useState(false)
  const [reenviado, setReenviado] = useState(false)

  /* Chegou aqui sem conta (link colado, aba velha): não há o que confirmar. */
  if (!user) return <Navigate to="/login?mode=register" replace />
  /* Já confirmou: o trial ou já saiu ou já foi usado, e esta tela viraria um
     beco. O produto é o destino certo nos dois casos. */
  if (user.email_verified === true) return <Navigate to="/picks" replace />

  const email = state?.email ?? user.email ?? ''

  const reenviar = async () => {
    setEnviando(true)
    try {
      await api.post('/auth/resend-verification')
      setReenviado(true)
    } catch {
      /* Silencioso: o e-mail original já saiu no cadastro, e um erro aqui não
         muda o que a pessoa precisa fazer, que é abrir a caixa de entrada. */
      setReenviado(true)
    } finally {
      setEnviando(false)
    }
  }

  return (
    <div className="relative min-h-screen bg-surface-0 flex flex-col overflow-hidden">
      <Helmet>
        <title>Confirme seu e-mail | Pick IA</title>
        <meta name="robots" content="noindex" />
      </Helmet>

      {/* Sem o par Entrar/Criar conta: quem está aqui acabou de criar a conta
          E já está autenticado, e os dois botões convidam para o que ela
          acabou de fazer. Fica só a saída. */}
      <PublicNav
        width="full"
        acoes={
          <Link
            to="/picks"
            className="text-sm text-ink-2 hover:text-ink-1 transition-colors px-3 py-2"
          >
            Ver os picks
          </Link>
        }
      />

      <main className="relative flex-1 flex justify-center px-5 sm:px-6 py-8 sm:py-12">
        <div className="relative w-full max-w-md">
          <div className="w-14 h-14 rounded-full bg-yellow-400/10 border border-yellow-400/30 flex items-center justify-center mb-5">
            <Crown className="w-6 h-6 text-yellow-400" aria-hidden="true" />
          </div>

          <h1 className="text-2xl font-bold text-ink-1 mb-2">
            Falta um clique para os 2 dias de VIP
          </h1>
          <p className="text-ink-3 text-sm leading-relaxed mb-6">
            Sua conta está criada. Mandamos um link para{' '}
            <strong className="text-ink-1 break-all">{email}</strong>: ao abrir, o acesso VIP
            completo liga na hora e vale por 2 dias.
          </p>

          <ul className="space-y-2.5 mb-6">
            {[
              'Picks VIP, múltiplas, alavancagem e ao vivo, tudo aberto',
              'Não pedimos dados de pagamento para testar',
              'O acesso vence sozinho, não cobramos nada no fim',
            ].map(t => (
              <li key={t} className="flex items-start gap-2.5">
                <Check className="w-4 h-4 text-accent-ink shrink-0 mt-0.5" aria-hidden="true" />
                <span className="text-sm text-ink-2 leading-snug">{t}</span>
              </li>
            ))}
          </ul>

          <div className="bg-surface-1 border border-line rounded-lg p-4 mb-6">
            <p className="flex items-center gap-2 text-xs text-ink-3 mb-3">
              <Mail className="w-4 h-4 text-ink-4 shrink-0" aria-hidden="true" />
              Não chegou? Confira o lixo eletrônico antes de pedir outro.
            </p>
            <button
              type="button"
              onClick={reenviar}
              disabled={enviando || reenviado}
              className="btn-ghost w-full text-sm min-h-[44px] disabled:opacity-60"
            >
              {reenviado ? 'Link reenviado' : enviando ? 'Enviando...' : 'Reenviar o link'}
            </button>
          </div>

          {/* O telefone é o outro caminho que paga o trial, e para quem digitou
              um e-mail com erro no cadastro ele é o único que resta. */}
          <p className="text-xs text-ink-4 leading-relaxed mb-6">
            Errou o e-mail? Dá para provar o contato pelo WhatsApp em{' '}
            <Link to="/perfil" className="text-ink-2 hover:text-ink-1 underline underline-offset-2">
              Meu perfil
            </Link>
            , e o trial sai do mesmo jeito.
          </p>

          <button
            type="button"
            onClick={() => navigate('/picks', { replace: true })}
            className="text-sm text-ink-3 hover:text-ink-1 transition-colors underline underline-offset-4"
          >
            Entrar sem confirmar agora
          </button>
          <p className="text-[11px] text-ink-4 mt-1.5">
            Você entra no plano free e o link continua valendo depois.
          </p>
        </div>
      </main>
    </div>
  )
}
