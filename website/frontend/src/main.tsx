import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

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
    <App />
  </React.StrictMode>
)
