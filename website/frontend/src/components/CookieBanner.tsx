import { useState, useEffect } from 'react'

export default function CookieBanner() {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (!localStorage.getItem('cookie_consent')) setVisible(true)
  }, [])

  const accept = () => {
    localStorage.setItem('cookie_consent', '1')
    setVisible(false)
  }

  if (!visible) return null

  return (
    <div className="fixed bottom-0 inset-x-0 z-40 bg-zinc-900 border-t border-zinc-800 px-4 py-4 sm:py-3"
      style={{ paddingBottom: 'calc(1rem + env(safe-area-inset-bottom))' }}>
      <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-start sm:items-center gap-3 sm:gap-6">
        <p className="text-xs text-zinc-400 flex-1 leading-relaxed">
          Usamos cookies essenciais para autenticação e funcionamento do site.
          Ao continuar, você concorda com nossa{' '}
          <a href="/privacidade" className="underline text-zinc-300 hover:text-white transition-colors">
            Política de Privacidade
          </a>.
        </p>
        <button
          onClick={accept}
          className="shrink-0 bg-green-500 hover:bg-green-400 active:bg-green-600 text-black text-xs font-black px-5 py-2 rounded-xl transition-colors"
        >
          Entendi
        </button>
      </div>
    </div>
  )
}
