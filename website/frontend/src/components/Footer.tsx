import { Link } from 'react-router-dom'
/* O Lucide tirou os ícones de marca (Instagram, X, etc.) por questão de
   trademark, então o do Instagram continua vindo do asset em /public. */
import { MessageCircle } from 'lucide-react'

/* Ícone do Instagram como SVG inline.
   Era um PNG de 164KB desenhado a 16x16 · sozinho pesava quase o mesmo que
   todo o JavaScript da página, e no celular isso se sente.
   Não vem do lucide-react porque a biblioteca removeu ícones de marca na v1.
   Desenhado no mesmo padrão do MessageCircle ao lado (viewBox 24, traço 2,
   currentColor) pra os dois ficarem idênticos em peso visual. */
function InstagramIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="2" y="2" width="20" height="20" rx="5" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="17.5" cy="6.5" r="185e-3" />
    </svg>
  )
}

/*
 * Rodapé do site.
 *
 * Sem a fita de ligas: ela é argumento de venda e o rodapé aparece nas 23
 * telas, inclusive nas de quem já assinou. Virou seção da Home, que é onde
 * ela tem função.
 *
 * O disclaimer de +18 e jogo responsável fica no rodapé de propósito: aparece
 * em todas as telas, que é o que a regra pede.
 */

const WA_SUPPORT =
  'https://wa.me/5517992323916?text=Ol%C3%A1!%20Preciso%20de%20suporte%20no%20Pick%20IA.'

const GROUPS: Array<{ title: string; links: Array<{ label: string; to?: string; href?: string }> }> = [
  {
    title: 'Produto',
    links: [
      { label: 'Picks do dia', to: '/picks' },
      { label: 'Resultados da IA', to: '/resultados' },
      { label: 'Performance da IA', to: '/performance' },
      { label: 'Jogos', to: '/fixtures' },
      { label: 'Como funciona', to: '/como-funciona' },
    ],
  },
  {
    title: 'Conta',
    links: [
      { label: 'Entrar', to: '/login' },
      { label: 'Criar conta grátis', to: '/login?mode=register' },
      { label: 'Planos', to: '/planos' },
      { label: 'Minha banca', to: '/banca' },
    ],
  },
  {
    title: 'Conteúdo',
    links: [
      { label: 'Blog', to: '/blog' },
      { label: 'Suporte', href: WA_SUPPORT },
    ],
  },
  {
    title: 'Legal',
    links: [
      { label: 'Termos de Uso', to: '/termos' },
      { label: 'Privacidade', to: '/privacidade' },
    ],
  },
]

export default function Footer() {
  return (
    <footer className="border-t border-line bg-surface-0 mt-auto">

      <div className="max-w-6xl mx-auto px-4 py-10">
        <div className="grid grid-cols-2 md:grid-cols-6 gap-8">

          {/* Marca */}
          <div className="col-span-2">
            <Link to="/" className="inline-flex items-center gap-2.5 mb-3 py-1" aria-label="Pick IA, início">
              <img src="/logo.png" alt="" width={30} height={30} className="w-[30px] h-[30px] rounded-full object-cover" />
              <span className="font-display text-base font-semibold text-ink-1">
                Pick<span className="text-accent">IA</span>
              </span>
            </Link>
            <p className="text-xs text-ink-3 leading-relaxed max-w-[34ch]">
              Inteligência artificial que analisa estatística real de futebol e publica
              apenas os picks com valor esperado positivo.
            </p>

            <div className="flex items-center gap-2 mt-4">
              <a
                href="https://www.instagram.com/pickia.br/"
                target="_blank"
                rel="noopener noreferrer"
                aria-label="Instagram do Pick IA"
                className="w-9 h-9 rounded-md border border-line flex items-center justify-center text-ink-3 hover:text-ink-1 hover:border-line-strong transition-colors duration-1 ease-smooth"
              >
                <InstagramIcon className="w-4 h-4" />
              </a>
              <a
                href={WA_SUPPORT}
                target="_blank"
                rel="noopener noreferrer"
                aria-label="Suporte por WhatsApp"
                className="w-9 h-9 rounded-md border border-line flex items-center justify-center text-ink-3 hover:text-ink-1 hover:border-line-strong transition-colors duration-1 ease-smooth"
              >
                <MessageCircle className="w-4 h-4" />
              </a>
            </div>
          </div>

          {GROUPS.map(({ title, links }) => (
            <div key={title}>
              <p className="label-micro mb-3">{title}</p>
              <ul className="space-y-0.5 -ml-1">
                {links.map(l => (
                  <li key={l.label}>
                    {l.to ? (
                      <Link to={l.to} className="block px-1 py-2.5 text-xs text-ink-3 hover:text-ink-1 transition-colors duration-1 ease-smooth">
                        {l.label}
                      </Link>
                    ) : (
                      <a
                        href={l.href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block px-1 py-2.5 text-xs text-ink-3 hover:text-ink-1 transition-colors duration-1 ease-smooth"
                      >
                        {l.label}
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-10 pt-6 border-t border-line flex flex-col sm:flex-row items-center justify-between gap-3">
          <p className="text-[11px] text-ink-4 text-center sm:text-left">
            {new Date().getFullYear()} © Pick IA. Picks gerados por inteligência artificial.
          </p>
          <p className="text-[11px] text-ink-4 text-center sm:text-right">
            Conteúdo para maiores de 18 anos. Aposte com responsabilidade.
          </p>
        </div>
      </div>
    </footer>
  )
}
