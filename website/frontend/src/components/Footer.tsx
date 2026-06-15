import { Link } from 'react-router-dom'

export default function Footer() {
  return (
    <footer className="border-t border-zinc-800 bg-zinc-950 mt-12">
      <div className="max-w-6xl mx-auto px-4 py-8">
        <div className="flex flex-col items-center gap-5 sm:flex-row sm:justify-between">

          {/* Logo + tagline */}
          <div className="flex items-center gap-2.5">
            <img src="/logo.png" alt="PickIA" className="w-7 h-7 rounded-full object-cover" />
            <span className="text-sm font-black text-zinc-300">Pick<span className="text-green-500">IA</span></span>
            <span className="text-xs text-zinc-600">· Copa do Mundo 2026</span>
          </div>

          {/* Links */}
          <div className="flex items-center gap-5 flex-wrap justify-center">
            <a
              href="https://www.instagram.com/hpstips/"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 text-xs text-zinc-500 hover:text-pink-400 transition-colors font-semibold"
            >
              <img src="/instagram.png" alt="Instagram" className="w-4 h-4 rounded-sm object-cover" />
              @hpstips
            </a>
            <Link to="/planos" className="text-xs text-zinc-500 hover:text-green-400 transition-colors">
              Planos
            </Link>
            <Link to="/results" className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors">
              Resultados
            </Link>
            <Link to="/termos" className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors">
              Termos de Uso
            </Link>
            <Link to="/privacidade" className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors">
              Privacidade
            </Link>
          </div>

          {/* Disclaimer */}
          <p className="text-xs text-zinc-700 text-center sm:text-right">
            Picks por IA. Aposte com responsabilidade. +18.
          </p>
        </div>
      </div>
    </footer>
  )
}
