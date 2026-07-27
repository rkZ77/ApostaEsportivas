import type { Transition, Variants } from 'framer-motion'

/** Easing/spring presets reaproveitados em todo o app · mantém a "sensação" consistente */
export const EASE_OUT: Transition = { duration: 0.25, ease: [0.16, 1, 0.3, 1] }
export const SPRING: Transition = { type: 'spring', stiffness: 420, damping: 34 }
export const SPRING_SOFT: Transition = { type: 'spring', stiffness: 300, damping: 30 }

/** Backdrop escuro atrás de modais/drawers */
export const backdropFade: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: EASE_OUT },
  exit: { opacity: 0, transition: { duration: 0.18 } },
}

/** Dialog central (scale + fade) · ApostaModal, FixtureStatsModal, MonthlyCloseModal */
export const dialogScale: Variants = {
  hidden: { opacity: 0, scale: 0.95, y: 8 },
  visible: { opacity: 1, scale: 1, y: 0, transition: SPRING },
  exit: { opacity: 0, scale: 0.96, y: 6, transition: { duration: 0.15 } },
}

/** Bottom sheet (sobe de baixo) · ApostaModal em mobile, ranking bottom-sheet */
export const sheetUp: Variants = {
  hidden: { opacity: 0, y: '100%' },
  visible: { opacity: 1, y: 0, transition: SPRING_SOFT },
  exit: { opacity: 0, y: '100%', transition: { duration: 0.2, ease: [0.4, 0, 1, 1] } },
}

/** Drawer lateral (desliza da direita) · SuggestionDetail */
export const drawerRight: Variants = {
  hidden: { opacity: 0, x: '100%' },
  visible: { opacity: 1, x: 0, transition: SPRING_SOFT },
  exit: { opacity: 0, x: '100%', transition: { duration: 0.2, ease: [0.4, 0, 1, 1] } },
}

/** Toast/banner fixo (sobe e desaparece) · ErrorToast, CookieBanner, PushPromptBanner, UpdateBanner */
export const toastUp: Variants = {
  hidden: { opacity: 0, y: 16, scale: 0.98 },
  visible: { opacity: 1, y: 0, scale: 1, transition: SPRING },
  exit: { opacity: 0, y: 12, scale: 0.98, transition: { duration: 0.15 } },
}

/** Tooltip pequeno (InfoTip) */
export const popIn: Variants = {
  hidden: { opacity: 0, scale: 0.9, y: 4 },
  visible: { opacity: 1, scale: 1, y: 0, transition: { duration: 0.15, ease: [0.16, 1, 0.3, 1] } },
  exit: { opacity: 0, scale: 0.92, transition: { duration: 0.1 } },
}

/** Item de card/lista (fade + leve subida) · usar com staggerContainer no pai */
export const fadeInUp: Variants = {
  hidden: { opacity: 0, y: 14 },
  visible: { opacity: 1, y: 0, transition: EASE_OUT },
}

/** Container de grid/lista com stagger nos filhos */
export const staggerContainer: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.06, delayChildren: 0.02 } },
}

/** Crossfade de conteúdo de aba (usar com AnimatePresence mode="wait" + key) */
export const tabFade: Variants = {
  hidden: { opacity: 0, y: 6 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.18, ease: [0.16, 1, 0.3, 1] } },
  exit: { opacity: 0, y: -6, transition: { duration: 0.12 } },
}

/** Tap feedback padrão para cards/botões clicáveis */
export const tapScale = { scale: 0.97 }
