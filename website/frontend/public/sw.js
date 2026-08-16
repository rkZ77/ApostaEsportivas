// Subir esta versao apaga o cache anterior inteiro no `activate` (ele remove
// toda chave diferente desta). E' o que garante que ninguem fique preso no
// index.html cache-first da versao antiga do proprio SW.
const CACHE = 'pickia-v2'
const STATIC = ['/manifest.json', '/favicon.png']

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(STATIC)))
  self.skipWaiting()
})

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  )
  self.clients.claim()
})

self.addEventListener('push', e => {
  const data = e.data?.json() ?? {}
  e.waitUntil(
    self.registration.showNotification(data.title ?? 'Pick IA', {
      body: data.body ?? '',
      icon: '/logo.png',
      badge: '/favicon.png',
      data: { url: data.url ?? '/picks' },
      requireInteraction: false,
    })
  )
})

self.addEventListener('notificationclick', e => {
  e.notification.close()
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(cs => {
      const target = e.notification.data?.url ?? '/picks'
      const found = cs.find(c => 'focus' in c)
      if (found) { found.focus(); return }
      return clients.openWindow(target)
    })
  )
})

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url)
  if (e.request.method !== 'GET') return
  if (url.pathname.startsWith('/api/')) return
  // So intercepta recursos do proprio site -- re-emitir fetch() de origem
  // cruzada (fonts.googleapis.com, googletagmanager.com, challenges.cloudflare.com)
  // de dentro do service worker cai sob connect-src do CSP (nao script-src/style-src),
  // bloqueando scripts/fontes de terceiros que carregariam normal sem o SW no meio.
  if (url.origin !== self.location.origin) return

  // HTML e' REDE PRIMEIRO. Cache primeiro pra navegacao foi o que fez o site
  // continuar mostrando a versao antiga depois de cada deploy: o index.html
  // guardado apontava pros bundles antigos, e como ele proprio saia do cache,
  // nunca havia motivo pra buscar o novo. O usuario via "o site nao atualizou"
  // e a unica saida era Ctrl+Shift+R.
  //
  // Os bundles do Vite tem hash no nome, entao pra eles cache primeiro e' certo
  // e barato: nome diferente = arquivo diferente, nunca serve conteudo velho.
  const ehNavegacao = e.request.mode === 'navigate' ||
    (e.request.headers.get('accept') || '').includes('text/html')

  if (ehNavegacao) {
    e.respondWith(
      fetch(e.request)
        .then(res => {
          if (res && res.status === 200) {
            const clone = res.clone()
            caches.open(CACHE).then(c => c.put(e.request, clone))
          }
          return res
        })
        // Offline: o cache vira rede de seguranca, que e' o papel dele aqui.
        .catch(() => caches.match(e.request).then(c => c ?? Response.error()))
    )
    return
  }

  e.respondWith(
    caches.match(e.request).then(cached => {
      const network = fetch(e.request).then(res => {
        if (res && res.status === 200) {
          const clone = res.clone()
          caches.open(CACHE).then(c => c.put(e.request, clone))
        }
        return res
      })
      return cached ?? network
    })
  )
})
