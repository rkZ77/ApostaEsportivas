import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <div className="min-h-screen bg-black flex flex-col items-center justify-center px-4 text-center">
      <p className="font-display text-green-500 font-black text-7xl mb-4">404</p>
      <h1 className="text-white font-black text-2xl mb-2">Página não encontrada</h1>
      <p className="text-zinc-500 text-sm mb-8 max-w-xs">
        O endereço que você acessou não existe ou foi removido.
      </p>
      <Link
        to="/"
        className="bg-green-500 hover:bg-green-400 text-black font-black px-7 py-3 rounded-md text-sm transition-colors"
      >
        Voltar ao início
      </Link>
    </div>
  )
}
