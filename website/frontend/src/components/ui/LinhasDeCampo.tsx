import { cn } from '../../lib/cn'

/*
 * LINHAS DE CAMPO NO FUNDO (15/10/2026, identidade visual).
 *
 * No lugar do brilho verde difuso e da grade quadriculada, que são o fundo de
 * todo template de IA: meio-campo, círculo central e as duas grandes áreas,
 * em traço fino e quase apagado. Diz "futebol" sem pedir atenção.
 *
 * SVG puro, sem filtro nem desfoque · não cria camada no Safari do iPhone,
 * que era o cuidado do brilho antigo. A máscara apaga as bordas pra o desenho
 * não terminar num corte seco.
 *
 * `foco` escolhe de onde o desenho nasce: 'topo' (hero), 'base' (fechamento).
 */
export default function LinhasDeCampo({ foco = 'topo', className }: {
  foco?: 'topo' | 'base' | 'centro'
  className?: string
}) {
  const mascara = foco === 'topo'
    ? 'radial-gradient(ellipse 70% 60% at 50% 0%, black, transparent 75%)'
    : foco === 'base'
      ? 'radial-gradient(ellipse 70% 70% at 50% 100%, black, transparent 75%)'
      : 'radial-gradient(ellipse 60% 60% at 50% 50%, black, transparent 75%)'
  return (
    <div
      aria-hidden="true"
      className={cn('pointer-events-none absolute inset-0 overflow-hidden text-accent/[0.14]', className)}
      style={{ maskImage: mascara, WebkitMaskImage: mascara }}
    >
      <svg
        className="absolute left-1/2 -translate-x-1/2 h-full min-w-[900px] w-full"
        viewBox="0 0 1050 680" preserveAspectRatio="xMidYMid slice"
        fill="none" stroke="currentColor" strokeWidth="2" vectorEffect="non-scaling-stroke"
      >
        {/* contorno e meio-campo */}
        <rect x="25" y="25" width="1000" height="630" />
        <line x1="525" y1="25" x2="525" y2="655" />
        {/* círculo central e ponto */}
        <circle cx="525" cy="340" r="91.5" />
        <circle cx="525" cy="340" r="3" fill="currentColor" />
        {/* grandes e pequenas áreas */}
        <rect x="25" y="138" width="165" height="404" />
        <rect x="25" y="248" width="55" height="184" />
        <rect x="860" y="138" width="165" height="404" />
        <rect x="970" y="248" width="55" height="184" />
        {/* meias-luas da área */}
        <path d="M190 280 A91.5 91.5 0 0 1 190 400" />
        <path d="M860 280 A91.5 91.5 0 0 0 860 400" />
      </svg>
    </div>
  )
}
