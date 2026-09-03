import { Link } from 'react-router-dom'
import { WA_SUPPORT } from '../lib/support'
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


/*
 * RODAPÉ CURTO, DE PROPÓSITO.
 *
 * Eram quatro colunas com quatorze links (Produto, Conta, Conteúdo, Legal) mais
 * a coluna da marca: um bloco mais alto que o conteúdo de algumas páginas, e no
 * celular isso vira uma tela inteira de lista antes do fim. Rodapé não é mapa do
 * site · é onde a pessoa procura o que não achou em cima.
 *
 * Ficou o que alguém realmente procura aqui: as duas telas públicas de prova, o
 * caminho pra assinar, suporte e o legal (que é obrigatório). O resto já está no
 * cabeçalho de todas as páginas.
 */
const LINKS: Array<{ label: string; to?: string; href?: string }> = [
  { label: 'Picks do dia',      to: '/picks' },
  /* Entra no rodapé, e não só no sitemap, porque é a página que responde a
     busca ("palpites de futebol hoje"): sem um link em todas as telas, ela
     seria a única página pública sem nada apontando pra ela. */
  { label: 'Palpites de hoje',  to: '/palpites-de-futebol-hoje' },
  { label: 'Resultados da IA',  to: '/resultados' },
  { label: 'Como funciona',     to: '/como-funciona' },
  { label: 'Planos',            to: '/planos' },
  { label: 'Suporte',           href: WA_SUPPORT },
  { label: 'Termos de Uso',     to: '/termos' },
  { label: 'Privacidade',       to: '/privacidade' },
]

export default function Footer() {
  return (
    <footer className="border-t border-line bg-surface-0 mt-auto">

      <div className="max-w-6xl mx-auto px-4 py-8">
        <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-6">

          {/* Marca */}
          <div className="min-w-0">
            <Link to="/" className="inline-flex items-center gap-2.5 mb-2 py-1" aria-label="Pick IA, início">
              <img src="/logo.png" alt="" width={28} height={28} className="w-7 h-7 rounded-full object-cover" />
              <span className="font-display text-base font-semibold text-ink-1">
                Pick<span className="text-accent-ink">IA</span>
              </span>
            </Link>
            <p className="text-xs text-ink-3 leading-relaxed max-w-[38ch]">
              Inteligência artificial que analisa estatística real de futebol e publica
              apenas os picks com valor esperado positivo.
            </p>
            <div className="flex items-center gap-2 mt-3">
              <a
                href="https://www.instagram.com/pickia.app/"
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

          {/* Links numa fita só · ver o comentário de LINKS */}
          <nav className="flex flex-wrap gap-x-5 gap-y-1 md:justify-end md:max-w-md">
            {LINKS.map(l => (
              l.to ? (
                <Link
                  key={l.label}
                  to={l.to}
                  className="py-1.5 text-xs text-ink-3 hover:text-ink-1 transition-colors duration-1 ease-smooth"
                >
                  {l.label}
                </Link>
              ) : (
                <a
                  key={l.label}
                  href={l.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="py-1.5 text-xs text-ink-3 hover:text-ink-1 transition-colors duration-1 ease-smooth"
                >
                  {l.label}
                </a>
              )
            ))}
          </nav>
        </div>

        <div className="mt-6 pt-5 border-t border-line flex flex-col sm:flex-row items-center justify-between gap-3">
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
