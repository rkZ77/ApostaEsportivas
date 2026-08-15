import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Crown, X } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { cn } from '../lib/cn'
import { PAGE_WIDTH, type PageWidth } from '../lib/pageWidth'

/*
 * Faixa de plano · logo abaixo da barra de título, dentro do PageShell.
 *
 * SÓ APARECE LOGADO, e nunca na Home: a Home não usa PageShell (monta a própria
 * casca), então a exclusão é estrutural, não um `if` que alguém pode esquecer de
 * atualizar. Nas telas públicas que USAM PageShell (Resultados, Performance,
 * pick compartilhado) ela aparece para quem está logado, e é justamente onde a
 * conversa faz sentido: o cara acabou de ver o histórico da IA.
 *
 * Três estados, nessa ordem de precedência:
 *   free              · não tem acesso, o convite é para conhecer o VIP
 *   trial             · tem acesso e vai perder, com a contagem à mostra
 *   vip perto de expirar · lembrete de renovação (5 dias ou menos)
 * VIP com folga e admin não veem nada. Fora de /checkout e /planos também não:
 * quem já está lá dentro não precisa ser convidado para ir.
 *
 * O nome do plano pago é "VIP" em todo o site (PlanBadge, Navbar, Checkout,
 * Planos). A faixa fala o mesmo nome de propósito: um apelido novo aqui criaria
 * um segundo vocabulário para o mesmo produto.
 *
 * Dá para dispensar, e a dispensa dura 24h (localStorage). Faixa fixa que não
 * fecha em toda tela do app vira ruído, e ruído a pessoa aprende a não ler.
 */

const SNOOZE_KEY = 'pickia_plan_upsell_snooze'
const SNOOZE_MS  = 24 * 60 * 60 * 1000

function adiadoAte(): number {
  const raw = localStorage.getItem(SNOOZE_KEY)
  const ts = raw ? Number(raw) : 0
  return Number.isFinite(ts) ? ts : 0
}

interface Convite {
  texto: React.ReactNode
  cta: string
  to: string
  /** Amarelo é o tom de VIP no site inteiro; âmbar puxa a urgência do trial. */
  tone: 'yellow' | 'amber'
}

export default function PlanUpsellBar({ width = 'default' }: { width?: PageWidth }) {
  const { user, isAdmin, daysUntilExpiry } = useAuth()
  const { pathname } = useLocation()
  const [dispensado, setDispensado] = useState(() => Date.now() < adiadoAte())

  if (!user || isAdmin || dispensado) return null
  if (pathname.startsWith('/checkout') || pathname.startsWith('/planos')) return null

  const dias = daysUntilExpiry
  const prazo = dias == null ? null
    : dias <= 0 ? 'hoje'
    : dias === 1 ? 'amanhã'
    : `em ${dias} dias`

  let convite: Convite | null = null

  if (user.plan === 'free') {
    convite = {
      texto: (
        <>
          Você está no <strong className="text-ink-1 font-semibold">plano gratuito</strong>
          {' '}· 1 pick por dia. O VIP abre todos os picks do dia.
        </>
      ),
      cta: 'Conhecer o VIP',
      to: '/planos',
      tone: 'yellow',
    }
  } else if (user.plan === 'trial') {
    convite = {
      texto: (
        <>
          Seu <strong className="text-ink-1 font-semibold">teste do VIP</strong>
          {prazo ? <> termina {prazo}</> : ' está em andamento'}
          . Assine para não perder o acesso.
        </>
      ),
      cta: 'Assinar VIP',
      to: '/checkout',
      tone: 'amber',
    }
  } else if (user.plan === 'vip' && dias != null && dias <= 5) {
    convite = {
      texto: (
        <>
          Seu <strong className="text-ink-1 font-semibold">VIP</strong> expira {prazo}.
          Renove para continuar com todos os picks.
        </>
      ),
      cta: 'Renovar',
      to: '/planos',
      tone: 'yellow',
    }
  }

  if (!convite) return null

  const dispensar = () => {
    localStorage.setItem(SNOOZE_KEY, String(Date.now() + SNOOZE_MS))
    setDispensado(true)
  }

  const cor = convite.tone === 'amber'
    ? { faixa: 'bg-amber-400/[0.07] border-amber-400/20', icone: 'text-amber-400',
        botao: 'text-amber-300 border-amber-400/30 hover:bg-amber-400/10' }
    : { faixa: 'bg-yellow-400/[0.07] border-yellow-400/20', icone: 'text-yellow-400',
        botao: 'text-yellow-300 border-yellow-400/30 hover:bg-yellow-400/10' }

  return (
    <div className={cn('border-b', cor.faixa)}>
      {/* Uma linha só no desktop; no mobile o texto quebra e o botão desce
          inteiro, nunca espremido. O X fica sempre na primeira linha. */}
      <div className={cn('mx-auto py-2.5 flex items-center gap-2.5 flex-wrap', PAGE_WIDTH[width])}>
        <Crown className={cn('w-4 h-4 shrink-0', cor.icone)} />
        <p className="text-xs text-ink-2 leading-snug flex-1 min-w-[12rem]">
          {convite.texto}
        </p>
        <Link
          to={convite.to}
          className={cn(
            'text-xs font-bold px-3 py-1.5 rounded-lg border transition-colors shrink-0',
            cor.botao,
          )}
        >
          {convite.cta}
        </Link>
        <button
          onClick={dispensar}
          aria-label="Dispensar por hoje"
          className="text-ink-4 hover:text-ink-2 transition-colors shrink-0 p-1 -mr-1"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  )
}
