import { Link } from 'react-router-dom'
/* O Lucide tirou os ícones de marca (Instagram, X, etc.) por questão de
   trademark, então o do Instagram continua vindo do asset em /public. */
import { MessageCircle } from 'lucide-react'
import LeagueMarquee from './LeagueMarquee'

/*
 * Rodapé do site.
 *
 * Acima dos links entra a fita de ligas cobertas: é a prova mais direta do que
 * a IA analisa, e o rodapé é onde ela cabe em toda página sem roubar espaço do
 * conteúdo.
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

      {/* Ligas cobertas */}
      <div className="border-b border-line py-4">
        <p className="label-micro text-center mb-3">Ligas e torneios cobertos</p>
        <LeagueMarquee muted />
      </div>

      <div className="max-w-6xl mx-auto px-4 py-10">
        <div className="grid grid-cols-2 md:grid-cols-6 gap-8">

          {/* Marca */}
          <div className="col-span-2">
            <Link to="/" className="flex items-center gap-2.5 mb-3" aria-label="Pick IA, início">
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
                <img src="/instagram.png" alt="" width={16} height={16} className="w-4 h-4 rounded-sm object-cover opacity-70" />
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
              <ul className="space-y-2">
                {links.map(l => (
                  <li key={l.label}>
                    {l.to ? (
                      <Link to={l.to} className="text-xs text-ink-3 hover:text-ink-1 transition-colors duration-1 ease-smooth">
                        {l.label}
                      </Link>
                    ) : (
                      <a
                        href={l.href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-ink-3 hover:text-ink-1 transition-colors duration-1 ease-smooth"
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
