import { useEffect, useRef } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Home, CalendarDays, BarChart3, Crown, Gift, Target } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { cn } from '../lib/cn'

/*
 * BARRA DE NAVEGAÇÃO INFERIOR DO CELULAR (2026-09-25).
 *
 * Veio da KaySto no celular: uma cápsula flutuando acima da borda da tela, com
 * os destinos principais ao alcance do polegar e um botão central maior. Só
 * existe abaixo de md; no desktop o cabeçalho já tem os links.
 *
 * O BOTÃO CENTRAL É A CHAMADA DE VENDA. Ele substituiu a faixa fixa "Testar o
 * Pro por 2 dias" que a Home tinha no rodapé do celular · as duas brigavam
 * pelo mesmo lugar. Pra visitante ele leva ao cadastro; pra quem já tem conta,
 * aos picks.
 *
 * A ALTURA VIRA VARIÁVEL. A barra publica `--barra-inferior` na raiz enquanto
 * está na tela; o body usa isso como folga (index.css) e os outros flutuantes
 * (avisos, Agente, banner de atualização) somam essa folga ao próprio `bottom`,
 * pra ninguém ficar escondido atrás dela.
 */

type Item = { to: string; label: string; Icon: LucideIcon }

const ESQUERDA: Item[] = [
  { to: '/',                          label: 'Início',    Icon: Home },
  { to: '/palpites-de-futebol-hoje',  label: 'Palpites',  Icon: CalendarDays },
]
const DIREITA: Item[] = [
  { to: '/resultados', label: 'Resultados', Icon: BarChart3 },
  { to: '/planos',     label: 'Planos',     Icon: Crown },
]

function Aba({ item, ativo }: { item: Item; ativo: boolean }) {
  const { to, label, Icon } = item
  return (
    <Link
      to={to}
      aria-current={ativo ? 'page' : undefined}
      className={cn(
        'flex-1 flex flex-col items-center justify-center gap-1 min-h-[52px] text-[10px] font-semibold transition-colors duration-1 ease-smooth',
        ativo ? 'text-accent-ink' : 'text-ink-3 hover:text-ink-1',
      )}
    >
      <span className={cn('w-9 h-7 rounded-lg flex items-center justify-center', ativo && 'bg-accent/15')}>
        <Icon className="w-[18px] h-[18px]" aria-hidden="true" />
      </span>
      {label}
    </Link>
  )
}

export default function BarraInferior() {
  const { user } = useAuth()
  const { pathname } = useLocation()
  const ref = useRef<HTMLElement>(null)

  useEffect(() => {
    const raiz = document.documentElement
    const el = ref.current
    if (!el) return
    // offsetHeight é 0 quando o md:hidden esconde a barra · aí a folga some junto.
    const publicar = () => {
      const h = el.offsetHeight
      if (h) raiz.style.setProperty('--barra-inferior', `${h + 12}px`)
      else raiz.style.removeProperty('--barra-inferior')
    }
    publicar()
    window.addEventListener('resize', publicar)
    return () => {
      window.removeEventListener('resize', publicar)
      raiz.style.removeProperty('--barra-inferior')
    }
  }, [])

  const central = user
    ? { to: '/picks', label: 'Picks', Icon: Target }
    : { to: '/login?mode=register', label: 'Grátis', Icon: Gift }

  return (
    <nav
      ref={ref}
      aria-label="Navegação rápida"
      className="md:hidden fixed inset-x-3 z-30 rounded-2xl border border-line bg-surface-0/85 backdrop-blur-xl shadow-elev"
      style={{ bottom: 'calc(0.75rem + env(safe-area-inset-bottom))' }}
    >
      <div className="flex items-center px-1.5 py-1.5">
        {ESQUERDA.map(i => <Aba key={i.to} item={i} ativo={pathname === i.to} />)}

        <Link
          to={central.to}
          className="flex-1 flex flex-col items-center justify-center gap-1 text-[10px] font-bold text-accent-ink"
        >
          <span className="-mt-7 w-14 h-14 rounded-full bg-accent hover:bg-accent-hover text-on-fill flex items-center justify-center shadow-elev ring-4 ring-surface-0 transition-colors duration-1 ease-smooth">
            <central.Icon className="w-6 h-6" aria-hidden="true" />
          </span>
          {central.label}
        </Link>

        {DIREITA.map(i => <Aba key={i.to} item={i} ativo={pathname === i.to} />)}
      </div>
    </nav>
  )
}
