import { useState, useEffect } from 'react'
import { AnimatePresence, m as motion } from 'framer-motion'

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
          /* A PILHA DE AVISOS PRECISA SABER QUE ESTA BARRA EXISTE.
            *
            * Ela e' uma barra de rodape inteira, e antes os avisos flutuantes
            * simplesmente caiam por cima dela (o toast de erro vivia em
            * `bottom-6`). So' este componente sabe se esta' na tela, entao e'
            * ele que publica a folga · ver PilhaDeAvisos. */
          ref={el => {
            const raiz = document.documentElement
            if (el) raiz.style.setProperty('--aviso-offset', `${el.offsetHeight}px`)
            else raiz.style.removeProperty('--aviso-offset')
          }}
          /* UMA LINHA NO CELULAR (20/10/2026): a barra em três andares cobria
             ~40% da tela. Lá o texto encurta e a política vira link na frase;
             do sm pra cima, o texto inteiro e o botão "Ler a política". */
          className="fixed bottom-0 inset-x-0 z-40 bg-surface-1 border-t border-line px-4 py-2.5 sm:py-3"
          style={{ paddingBottom: 'calc(0.625rem + env(safe-area-inset-bottom))' }}
        >
          <div className="max-w-5xl mx-auto flex flex-row items-center gap-3 sm:gap-6">
            <p className="sm:hidden text-[11px] text-ink-2 flex-1 leading-snug">
              Usamos cookies essenciais.{' '}
              <a href="/privacidade" className="underline underline-offset-2 text-ink-1">Política de privacidade</a>
            </p>
            <p className="hidden sm:block text-xs text-ink-2 flex-1 leading-relaxed">
              Usamos cookies essenciais para autenticação e funcionamento do site.
              Ao continuar, você concorda com nossa Política de Privacidade.
            </p>
            {/* A política saiu de dentro da frase e virou botão ao lado do
                "Entendi": ler antes de aceitar é uma escolha, não uma nota de
                rodapé sublinhada. */}
            <a
              href="/privacidade"
              className="hidden sm:inline-flex shrink-0 items-center justify-center text-xs font-bold text-ink-2 hover:text-ink-1 border border-line-strong hover:border-ink-4 px-4 py-2 rounded-lg min-h-[36px] transition-colors"
            >
              Ler a política
            </a>
            <motion.button
              whileTap={{ scale: 0.96 }}
              onClick={accept}
              className="shrink-0 bg-green-500 hover:bg-green-400 active:bg-green-600 text-black text-xs font-black px-5 min-h-[40px] rounded-lg transition-colors"
            >
              Entendi
            </motion.button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
