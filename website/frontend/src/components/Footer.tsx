import { Link } from 'react-router-dom'

export default function Footer() {
  return (
    <footer className="border-t border-line bg-surface-0 mt-12">
      <div className="max-w-6xl mx-auto px-4 py-8">
        <div className="flex flex-col items-center gap-5 sm:flex-row sm:justify-between">

          {/* Logo + tagline */}
          <div className="flex items-center gap-2.5">
            <img src="/logo.png" alt="PickIA" width={28} height={28} className="w-7 h-7 rounded-full object-cover" />
            <span className="font-display text-sm font-semibold text-ink-2">Pick<span className="text-green-500">IA</span></span>
          </div>

          {/* Links */}
          <div className="flex items-center gap-5 flex-wrap justify-center">
            <a
              href="https://www.instagram.com/pickia.br/"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 text-xs text-ink-3 hover:text-pink-400 transition-colors font-semibold"
            >
              <img src="/instagram.png" alt="Instagram" width={16} height={16} className="w-4 h-4 rounded-sm object-cover" />
              @pickia.br
            </a>
            <Link to="/planos" className="text-xs text-ink-3 hover:text-green-400 transition-colors">
              Planos
            </Link>
            <Link to="/resultados" className="text-xs text-ink-3 hover:text-ink-2 transition-colors">
              Resultados
            </Link>
            <Link to="/blog" className="text-xs text-ink-3 hover:text-ink-2 transition-colors">
              Blog
            </Link>
            <Link to="/termos" className="text-xs text-ink-3 hover:text-ink-2 transition-colors">
              Termos de Uso
            </Link>
            <Link to="/privacidade" className="text-xs text-ink-3 hover:text-ink-2 transition-colors">
              Privacidade
            </Link>
            <a
              href="https://wa.me/5517992323916?text=Ol%C3%A1!%20Preciso%20de%20suporte%20no%20Pick%20IA."
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-ink-3 hover:text-green-400 transition-colors font-semibold"
            >
              Suporte
            </a>
          </div>

          {/* Disclaimer */}
          <p className="text-xs text-ink-4 text-center sm:text-right">
            Picks por IA. Aposte com responsabilidade. +18.
          </p>
        </div>
      </div>
    </footer>
  )
}
