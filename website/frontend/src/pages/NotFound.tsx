import { Helmet } from 'react-helmet-async'
import { Compass } from 'lucide-react'
import { Button } from '../components/ui'

export default function NotFound() {
  return (
    <div className="min-h-screen bg-surface-0 flex flex-col items-center justify-center px-4 text-center">
      <Helmet>
        <title>Página não encontrada · Pick IA</title>
        {/* 404 fora do índice: sem isso o Google guarda a URL quebrada. */}
        <meta name="robots" content="noindex, nofollow" />
      </Helmet>

      <div className="w-12 h-12 rounded-lg border border-line flex items-center justify-center mb-6">
        <Compass className="w-6 h-6 text-ink-4" />
      </div>

      <p className="font-mono text-accent font-bold text-5xl mb-3 tabular-nums">404</p>
      <h1 className="font-display text-ink-1 font-bold text-xl mb-2">Página não encontrada</h1>
      <p className="text-ink-3 text-sm mb-8 max-w-xs leading-relaxed">
        O endereço que você acessou não existe ou foi removido.
      </p>

      <div className="flex flex-wrap items-center justify-center gap-3">
        <Button to="/">Voltar ao início</Button>
        <Button to="/resultados" variant="ghost">Ver resultados da IA</Button>
      </div>
    </div>
  )
}
