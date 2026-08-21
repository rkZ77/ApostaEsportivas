import { Helmet } from 'react-helmet-async'
import { motion, useReducedMotion } from 'framer-motion'
import { Button } from '../components/ui'

/*
 * A bola que faz o "0" do 404.
 *
 * Desenhada aqui em SVG, e não trazida como imagem, por três motivos: escala
 * sem borrar em qualquer tela, pesa menos de 2 KB dentro do próprio bundle
 * (uma página de erro não deveria custar uma requisição de rede a mais,
 * justamente quando algo já falhou) e as cores saem dos tokens do site, então
 * ela acompanha qualquer mudança de identidade sem alguém precisar reexportar
 * um arquivo.
 *
 * A fratura é uma fenda em ziguezague no meio: as duas metades usam o MESMO
 * desenho, recortado por dois clip-paths complementares e afastado alguns
 * pixels para cada lado. Desenhar duas metades separadas à mão faria as
 * costuras não baterem na hora de juntar.
 */
function BolaRachada({ className = '' }: { className?: string }) {
  // Ziguezague que corta a bola de cima a baixo · o mesmo traço serve de
  // borda para as duas metades, invertendo qual lado fica preenchido.
  const FENDA = '62 0 55 26 66 44 54 62 65 82 56 104 60 120'
  const bola = (
    <>
      <circle cx="60" cy="60" r="52" fill="rgb(var(--accent))" />
      {/* Sombra interna curta na base, pra bola não ficar chapada */}
      <circle cx="60" cy="60" r="52" fill="url(#volume404)" />
      <g clipPath="url(#recorte404)">
        {/* Pentágono central */}
        <polygon points="60,44 75.2,55.1 69.4,72.9 50.6,72.9 44.8,55.1"
          fill="rgb(var(--surface-0))" />
        {/* Costuras saindo de cada vértice até a borda */}
        <g stroke="rgb(var(--surface-0))" strokeWidth="3.4" strokeLinecap="round">
          <line x1="60" y1="44" x2="60" y2="8" />
          <line x1="75.2" y1="55.1" x2="109.4" y2="44.1" />
          <line x1="69.4" y1="72.9" x2="90.6" y2="102.1" />
          <line x1="50.6" y1="72.9" x2="29.4" y2="102.1" />
          <line x1="44.8" y1="55.1" x2="10.6" y2="44.1" />
        </g>
        {/* Pentágonos de borda, cortados pelo círculo */}
        <g fill="rgb(var(--surface-0))">
          <polygon points="60,-4 70,4 66,16 54,16 50,4" />
          <polygon points="114,40 122,50 114,60 103,55 105,44" />
          <polygon points="94,104 84,113 74,104 80,94 90,96" />
          <polygon points="46,104 36,113 26,104 32,94 42,96" />
          <polygon points="6,40 -2,50 6,60 17,55 15,44" />
        </g>
      </g>
      <circle cx="60" cy="60" r="52" fill="none"
        stroke="rgb(var(--surface-0))" strokeWidth="3" strokeOpacity="0.5" />
    </>
  )

  return (
    <svg viewBox="-6 0 132 120" className={className} aria-hidden="true">
      <defs>
        {/* Recorta tudo o que é costura para dentro da bola */}
        <clipPath id="recorte404">
          <circle cx="60" cy="60" r="52" />
        </clipPath>
        <clipPath id="metadeEsq404">
          <polygon points={`-6 0 ${FENDA} -6 120`} />
        </clipPath>
        <clipPath id="metadeDir404">
          <polygon points={`126 0 ${FENDA} 126 120`} />
        </clipPath>
        <radialGradient id="volume404" cx="35%" cy="30%" r="75%">
          <stop offset="0%" stopColor="#fff" stopOpacity="0.22" />
          <stop offset="55%" stopColor="#fff" stopOpacity="0" />
          <stop offset="100%" stopColor="#000" stopOpacity="0.35" />
        </radialGradient>
      </defs>

      <g clipPath="url(#metadeEsq404)" transform="translate(-2.5 0)">{bola}</g>
      <g clipPath="url(#metadeDir404)" transform="translate(2.5 0)">{bola}</g>

      {/* Cacos soltos na fenda · o que sobra de uma bola que estourou */}
      <g fill="rgb(var(--accent))">
        <polygon points="58,50 63,53 59,57" opacity="0.9" />
        <polygon points="64,66 69,70 63,72" opacity="0.75" />
        <polygon points="53,76 57,79 52,81" opacity="0.6" />
        <polygon points="62,36 66,38 62,41" opacity="0.5" />
      </g>
    </svg>
  )
}

export default function NotFound() {
  const semMovimento = useReducedMotion()

  return (
    <div className="min-h-screen bg-surface-0 flex flex-col items-center justify-center px-4 text-center">
      <Helmet>
        <title>Página não encontrada · Pick IA</title>
        {/* 404 fora do índice: sem isso o Google guarda a URL quebrada. */}
        <meta name="robots" content="noindex, nofollow" />
      </Helmet>

      {/* O número é texto de verdade, não desenho: leitor de tela e busca
          continuam lendo "404". A bola entra no lugar do zero, e por isso ela
          é `aria-hidden` · anunciar "imagem de bola" no meio do número faria a
          leitura sair picada. */}
      <h1 className="flex items-center justify-center gap-1 sm:gap-2 mb-6" aria-label="404">
        <span aria-hidden="true" className="font-display font-black text-ink-4/40 text-[5.5rem] sm:text-[8rem] leading-none select-none">4</span>
        <motion.span
          aria-hidden="true"
          initial={semMovimento ? false : { scale: 0.7, opacity: 0, rotate: -18 }}
          animate={{ scale: 1, opacity: 1, rotate: 0 }}
          transition={{ type: 'spring', stiffness: 260, damping: 18 }}
          className="block w-[5.4rem] sm:w-[7.8rem] shrink-0"
        >
          <BolaRachada className="w-full h-auto drop-shadow-[0_0_28px_rgba(0,204,0,0.28)]" />
        </motion.span>
        <span aria-hidden="true" className="font-display font-black text-ink-4/40 text-[5.5rem] sm:text-[8rem] leading-none select-none">4</span>
      </h1>

      <p className="font-display text-ink-1 font-bold text-xl mb-2">Essa bola foi pra fora</p>
      <p className="text-ink-3 text-sm mb-8 max-w-xs leading-relaxed">
        O endereço que você abriu não existe ou saiu do ar. Os picks de hoje
        continuam no lugar de sempre.
      </p>

      <div className="flex flex-wrap items-center justify-center gap-3">
        <Button to="/">Voltar ao início</Button>
        <Button to="/resultados" variant="ghost">Ver resultados da IA</Button>
      </div>
    </div>
  )
}
