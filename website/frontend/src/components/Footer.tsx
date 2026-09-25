import { Link } from 'react-router-dom'
import { WA_SUPPORT } from '../lib/support'
/* O Lucide tirou os ícones de marca (Instagram, X, etc.) por questão de
   trademark, então o do Instagram continua vindo do asset em /public. */
import { MessageCircle, Headphones, ShieldCheck, Lock } from 'lucide-react'

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
  { label: 'Resultado Geral',   to: '/resultados' },
  { label: 'Como funciona',     to: '/como-funciona' },
  { label: 'Planos',            to: '/planos' },
  { label: 'Suporte',           href: WA_SUPPORT },
  { label: 'Termos de Uso',     to: '/termos' },
  { label: 'Privacidade',       to: '/privacidade' },
]

/* Estilo do ícone social · os dois (Instagram e WhatsApp) são iguais. */
const SOCIAL = 'w-10 h-10 rounded-lg border border-line bg-surface-1 flex items-center justify-center text-ink-3 hover:text-ink-1 hover:border-line-strong transition-colors duration-1 ease-smooth'

/*
 * TRÊS COLUNAS (2026-09-25), no molde do rodapé da KaySto: marca com o selo
 * de confiança, a navegação, e um "Conecte-se" com o botão de suporte bem à
 * vista. Os mesmos links de antes · o que mudou foi a leitura: em coluna o
 * olho acha o link, numa fita corrida ele precisava ler um por um.
 */
export default function Footer() {
  return (
    <footer className="border-t border-line bg-surface-0 mt-auto">

      <div className="max-w-6xl mx-auto px-4 pt-10 pb-6">
        <div className="grid gap-8 md:grid-cols-[1.4fr_1fr_1fr]">

          {/* Marca */}
          <div className="min-w-0">
            <Link to="/" className="inline-flex items-center gap-3 mb-3" aria-label="Pick IA, início">
              <span className="w-10 h-10 rounded-lg border border-line bg-surface-1 flex items-center justify-center">
                <img src="/logo-64.webp" alt="" width={28} height={28} className="w-7 h-7 rounded-full object-cover" />
              </span>
              <span className="font-display text-lg font-semibold text-ink-1">
                Pick<span className="text-accent-ink">IA</span>
              </span>
            </Link>
            <p className="text-sm text-ink-3 leading-relaxed max-w-[44ch]">
              Com o <span className="text-accent-ink font-medium">Pick IA</span> você recebe só os
              picks que passaram no corte: inteligência artificial em cima de estatística real
              de futebol, publicando apenas o que tem valor esperado positivo.
            </p>

            <p className="mt-5 mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-4">
              Selos de confiança
            </p>
            <div className="flex flex-wrap gap-2">
              <Link
                to="/resultados"
                className="inline-flex items-center gap-2 rounded-md border border-line bg-surface-1 px-3 py-2 text-xs font-semibold text-ink-2 hover:text-ink-1 hover:border-line-strong transition-colors duration-1 ease-smooth"
              >
                <ShieldCheck className="w-4 h-4 text-accent-ink" aria-hidden="true" />
                Histórico 100% público
              </Link>
              <span className="inline-flex items-center gap-2 rounded-md border border-line bg-surface-1 px-3 py-2 text-xs font-semibold text-ink-2">
                <Lock className="w-4 h-4 text-accent-ink" aria-hidden="true" />
                Pagamento via MercadoPago
              </span>
            </div>
          </div>

          {/* Navegação. `py-2` mantém o alvo de toque acima dos 24px da
              WCAG 2.2 · o público é de celular. */}
          <nav aria-label="Rodapé">
            <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-4">Navegação</p>
            <ul className="grid grid-cols-2 md:grid-cols-1 gap-x-4">
              {LINKS.map(l => (
                <li key={l.label}>
                  {l.to ? (
                    <Link to={l.to} className="block py-2 text-sm text-ink-3 hover:text-ink-1 transition-colors duration-1 ease-smooth">
                      {l.label}
                    </Link>
                  ) : (
                    <a href={l.href} target="_blank" rel="noopener noreferrer" className="block py-2 text-sm text-ink-3 hover:text-ink-1 transition-colors duration-1 ease-smooth">
                      {l.label}
                    </a>
                  )}
                </li>
              ))}
            </ul>
          </nav>

          {/* Conecte-se */}
          <div>
            <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-4">Conecte-se</p>
            <div className="flex items-center gap-2.5">
              <a
                href="https://www.instagram.com/pickia.app/"
                target="_blank"
                rel="noopener noreferrer"
                aria-label="Instagram do Pick IA"
                className={SOCIAL}
              >
                <InstagramIcon className="w-[18px] h-[18px]" />
              </a>
              <a
                href={WA_SUPPORT}
                target="_blank"
                rel="noopener noreferrer"
                aria-label="WhatsApp do Pick IA"
                className={SOCIAL}
              >
                <MessageCircle className="w-[18px] h-[18px]" />
              </a>
            </div>
            <a
              href={WA_SUPPORT}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-4 inline-flex items-center gap-2 rounded-lg border border-accent/40 bg-accent/10 px-4 min-h-[44px] text-sm font-semibold text-accent-ink hover:bg-accent/15 transition-colors duration-1 ease-smooth"
            >
              <Headphones className="w-4 h-4" aria-hidden="true" />
              Falar com o suporte
            </a>
          </div>
        </div>

        <div className="mt-8 pt-5 border-t border-line flex flex-col sm:flex-row items-center justify-between gap-2">
          <p className="text-[11px] text-ink-4 text-center sm:text-left">
            © {new Date().getFullYear()} Pick IA. Todos os direitos reservados. Conteúdo para maiores de 18 anos · aposte com responsabilidade.
          </p>
          <p className="text-[11px] text-ink-4 text-center sm:text-right">
            Pix · Cartão · Boleto
          </p>
        </div>
      </div>
    </footer>
  )
}
