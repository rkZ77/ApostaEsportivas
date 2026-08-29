import { useState, useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'

export default function CookieBanner() {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (!localStorage.getItem('cookie_consent')) setVisible(true)
  }, [])

  const accept = () => {
    localStorage.setItem('cookie_consent', '1')
    setVisible(false)
    window.dispatchEvent(new Event('cookie-consent-accepted'))
  }

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ y: '100%' }}
          animate={{ y: 0 }}
          exit={{ y: '100%' }}
          transition={{ type: 'spring', stiffness: 300, damping: 32 }}
          className="fixed bottom-0 inset-x-0 z-40 bg-surface-1 border-t border-line px-4 py-4 sm:py-3"
          style={{ paddingBottom: 'calc(1rem + env(safe-area-inset-bottom))' }}
        >
          <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-start sm:items-center gap-3 sm:gap-6">
            <p className="text-xs text-ink-2 flex-1 leading-relaxed">
              Usamos cookies essenciais para autenticação e funcionamento do site.
              Ao continuar, você concorda com nossa Política de Privacidade.
            </p>
            {/* A política saiu de dentro da frase e virou botão ao lado do
                "Entendi": ler antes de aceitar é uma escolha, não uma nota de
                rodapé sublinhada. */}
            <a
              href="/privacidade"
              className="shrink-0 inline-flex items-center justify-center text-xs font-bold text-ink-2 hover:text-ink-1 border border-line-strong hover:border-ink-4 px-4 py-2 rounded-lg min-h-[36px] transition-colors"
            >
              Ler a política
            </a>
            <motion.button
              whileTap={{ scale: 0.96 }}
              onClick={accept}
              className="shrink-0 bg-green-500 hover:bg-green-400 active:bg-green-600 text-black text-xs font-black px-5 py-2 rounded-lg transition-colors"
            >
              Entendi
            </motion.button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
