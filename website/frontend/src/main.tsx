import React from 'react'
import ReactDOM from 'react-dom/client'
import { LazyMotion } from 'framer-motion'
import App from './App'
import './index.css'

/*
 * ANIMAÇÃO SEM PESAR NA PRIMEIRA TELA (2026-10-06).
 *
 * O site usava `motion.*`, que embute o motor de animação inteiro no
 * componente: 131 KB (43 KB comprimidos) baixados e executados antes de a
 * Home existir, sem animar nada que importe pro primeiro quadro. O PageSpeed
 * simula o LCP contando todo JavaScript que roda antes dele, e era essa conta
 * que deixava o LCP de laboratório em 4 s mesmo com o hero pré-renderizado.
 *
 * Agora todo componente usa `m` (importado como `m as motion`, então o JSX
 * não mudou) e o motor chega por `import()`, depois. `strict` faz um
 * `motion.*` completo esquecido em algum arquivo novo dar erro na hora, em vez
 * de trazer os 131 KB de volta calado.
 */
const recursosDeAnimacao = () => import('./lib/motionRecursos').then(r => r.default)

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {})
  })
}

// Depois de um deploy, uma aba aberta antes da troca de build tenta buscar um
// chunk JS com hash que nao existe mais no servidor. O Vite dispara esse evento
// nesse caso -- um reload busca a pagina nova, que ja aponta pros chunks certos.
// Mesma chave de sessionStorage do guard em App.tsx (RouteErrorBoundary) pra nao
// recarregar duas vezes pelo mesmo motivo.
window.addEventListener('vite:preloadError', () => {
  const last = Number(sessionStorage.getItem('pickia_chunk_reload_at') || 0)
  if (Date.now() - last < 10_000) return
  sessionStorage.setItem('pickia_chunk_reload_at', String(Date.now()))
  window.location.reload()
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <LazyMotion features={recursosDeAnimacao} strict>
      <App />
    </LazyMotion>
  </React.StrictMode>
)
